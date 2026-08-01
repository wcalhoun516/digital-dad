"""Embedding-model comparison harness (roadmap #27).

The corpus embedding model is **pinned** to ``sbert-mpnet-v2`` (decision D2):
cosine similarity is only meaningful within one vector space, so Semantic
Search, Ask Dad retrieval, and On This Day matching must all share it. Swapping
the model invalidates the whole index — so before we ever change it we need
numbers, not vibes. This module is that measurement mechanism.

Following ``analysis.rag_eval`` / ``analysis.voice_eval``, the compute-heavy,
networked part (actually embedding text through the conductor with a candidate
model) is isolated behind a single injected seam so all of the scoring and
comparison math is pure and unit-testable offline:

- ``embed(model_id, texts) -> list[vector]`` — embed a batch with one model.

Everything else — cosine ranking, retrieval-quality metrics (precision@k,
recall@k, MRR) against a small gold query set, and *baseline-agreement* metrics
(top-k overlap / Kendall-tau vs. the pinned model, which need no hand labels) —
are pure functions. The CLI (``python -m analysis.embedding_compare`` /
``make embedding-compare``) wires the seam to the live conductor and is gated on
its reachability because a live pass loads/embeds with each candidate model.

The dashboard viz and a curated gold query set are deferred to future slices;
this ships the offline harness + a starter query template.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .conductor import require_conductor
from .utils import DATA_DIR, clean_text, load_articles

# Repo-root-relative fixture (source-controlled input, not a generated artifact).
QUERIES_PATH = Path(__file__).resolve().parent.parent / "eval" / "embedding_queries.json"
REPORT_PATH = DATA_DIR / "analysis" / "embedding_compare.json"

# The pinned production embedder — the default baseline every candidate is
# measured against (decision D2).
BASELINE_MODEL = "sbert-mpnet-v2"
CONDUCTOR_BASE_URL = "http://127.0.0.1:8080/v1"

DEFAULT_KS = (1, 3, 5)

# mpnet's encoder context is short; the first ~2k words carry an article's gist
# (mirrors analysis.semantic_search._MAX_WORDS_PER_ARTICLE).
_MAX_WORDS_PER_ARTICLE = 2000


# --------------------------------------------------------------------------- #
# Ranking core (pure)
# --------------------------------------------------------------------------- #

def rank_slugs(
    query_vec: np.ndarray, corpus: np.ndarray, corpus_slugs: list[str]
) -> list[str]:
    """Return ``corpus_slugs`` ordered by descending cosine similarity to *query_vec*.

    Cosine ignores vector magnitude, so a scaled query yields the same order. A
    zero query (or zero corpus rows) can't define an angle — the ``1e-10`` guard
    keeps it finite and simply leaves those similarities at 0 rather than NaN.
    """
    query_vec = np.asarray(query_vec, dtype=np.float64)
    corpus = np.asarray(corpus, dtype=np.float64)
    norms = np.linalg.norm(corpus, axis=1)
    qnorm = np.linalg.norm(query_vec)
    sims = (corpus @ query_vec) / (norms * qnorm + 1e-10)
    order = np.argsort(sims)[::-1]
    return [corpus_slugs[i] for i in order]


# --------------------------------------------------------------------------- #
# Retrieval-quality metrics (pure) — need a gold {query: relevant_slugs} set
# --------------------------------------------------------------------------- #

def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top-``k`` retrieved slugs that are relevant.

    Denominator is ``min(k, len(ranked))`` so a short ranking isn't unfairly
    penalised for slots that don't exist.
    """
    if not ranked or k <= 0:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for s in top if s in relevant)
    return hits / len(top)


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the relevant slugs that appear in the top-``k``."""
    if not relevant:
        return 0.0
    top = set(ranked[:k])
    hits = sum(1 for s in relevant if s in top)
    return hits / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    """Reciprocal of the 1-based rank of the first relevant slug (0 if none)."""
    for i, slug in enumerate(ranked, 1):
        if slug in relevant:
            return 1.0 / i
    return 0.0


def mrr(rankings: list[list[str]], relevants: list[set[str]]) -> float:
    """Mean reciprocal rank over queries that have at least one relevant slug."""
    scored = [
        reciprocal_rank(r, rel)
        for r, rel in zip(rankings, relevants)
        if rel
    ]
    return sum(scored) / len(scored) if scored else 0.0


def retrieval_metrics(
    rankings: list[list[str]],
    relevants: list[set[str]],
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict:
    """Aggregate precision@k / recall@k / MRR over the labelled queries.

    Queries with no relevant slugs are unscorable and excluded from every mean
    (so an unlabelled query can't drag precision toward 0).
    """
    scored = [(r, rel) for r, rel in zip(rankings, relevants) if rel]
    out: dict = {"n_scored": len(scored)}
    for k in ks:
        if scored:
            out[f"precision_at_{k}"] = round(
                sum(precision_at_k(r, rel, k) for r, rel in scored) / len(scored), 4
            )
            out[f"recall_at_{k}"] = round(
                sum(recall_at_k(r, rel, k) for r, rel in scored) / len(scored), 4
            )
        else:
            out[f"precision_at_{k}"] = 0.0
            out[f"recall_at_{k}"] = 0.0
    out["mrr"] = round(mrr(rankings, relevants), 4)
    return out


# --------------------------------------------------------------------------- #
# Baseline-agreement metrics (pure) — no labels needed
# --------------------------------------------------------------------------- #

def overlap_at_k(ranked_a: list[str], ranked_b: list[str], k: int) -> float:
    """Jaccard overlap of the two top-``k`` slug sets (1.0 = identical members)."""
    a = set(ranked_a[:k])
    b = set(ranked_b[:k])
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def kendall_tau(ranked_a: list[str], ranked_b: list[str]) -> float:
    """Kendall-tau rank correlation over the items common to both rankings.

    +1 = same order, -1 = reversed, 0 = no correlation (or <2 shared items).
    Only shared items are considered, so two rankings over slightly different
    slug sets can still be compared on their common ground.
    """
    common = [s for s in ranked_a if s in set(ranked_b)]
    if len(common) < 2:
        return 0.0
    rank_b = {slug: i for i, slug in enumerate(ranked_b)}
    concordant = discordant = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            # common is in a's order, so i precedes j in a by construction.
            if rank_b[common[i]] < rank_b[common[j]]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 0.0


def agreement(
    rankings_a: list[list[str]],
    rankings_b: list[list[str]],
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict:
    """Mean top-k overlap + mean Kendall-tau of *a*'s rankings vs *b*'s, per query."""
    n = len(rankings_a)
    out: dict = {}
    for k in ks:
        vals = [overlap_at_k(a, b, k) for a, b in zip(rankings_a, rankings_b)]
        out[f"mean_overlap_at_{k}"] = round(sum(vals) / n, 4) if n else 0.0
    taus = [kendall_tau(a, b) for a, b in zip(rankings_a, rankings_b)]
    out["mean_kendall_tau"] = round(sum(taus) / n, 4) if n else 0.0
    return out


# --------------------------------------------------------------------------- #
# Harness (injected embed seam)
# --------------------------------------------------------------------------- #

def rank_model(
    model_id: str,
    corpus: list[dict],
    queries: list[dict],
    embed: Callable[[str, list[str]], list[list[float]]],
) -> list[list[str]]:
    """Embed the corpus + queries with *model_id* and return ranked slugs per query.

    A single ``embed(model_id, texts)`` call is made for the corpus and one for
    the queries (two calls per model), keeping the live conductor path cheap.
    """
    corpus_slugs = [c.get("slug") for c in corpus]
    corpus_mat = np.asarray(embed(model_id, [c.get("text", "") for c in corpus]), dtype=np.float64)
    query_mat = embed(model_id, [q.get("query", "") for q in queries])
    return [rank_slugs(np.asarray(qv, dtype=np.float64), corpus_mat, corpus_slugs) for qv in query_mat]


def compare_models(
    model_ids: list[str],
    corpus: list[dict],
    queries: list[dict],
    embed: Callable[[str, list[str]], list[list[float]]],
    *,
    baseline: str | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Rank the corpus per query with each model; score retrieval + baseline agreement.

    ``embed`` is injected so the loop is fully testable offline. ``baseline``
    (default: the first model id) is the model every other is compared against
    for ranking agreement; the baseline's own ``agreement`` is ``None``.
    """
    if not model_ids:
        return []
    baseline = baseline or model_ids[0]
    relevants = [set(q.get("relevant_slugs") or []) for q in queries]

    rankings_by_model: dict[str, list[list[str]]] = {}
    for model_id in model_ids:
        log(f"  embedding + ranking with {model_id} …")
        rankings_by_model[model_id] = rank_model(model_id, corpus, queries, embed)

    base_rankings = rankings_by_model.get(baseline)
    records: list[dict] = []
    for model_id in model_ids:
        rankings = rankings_by_model[model_id]
        is_baseline = model_id == baseline
        records.append(
            {
                "model": model_id,
                "is_baseline": is_baseline,
                "retrieval": retrieval_metrics(rankings, relevants, ks),
                "agreement": None
                if is_baseline or base_rankings is None
                else agreement(rankings, base_rankings, ks),
            }
        )
    return records


def aggregate(records: list[dict], baseline: str | None = None) -> dict:
    """Headline summary: model count, baseline id, and the best model by MRR."""
    best_model = None
    best_mrr = -1.0
    for r in records:
        m = r.get("retrieval", {}).get("mrr", 0.0)
        if m > best_mrr:
            best_mrr, best_model = m, r.get("model")
    return {
        "baseline": baseline,
        "n_models": len(records),
        "best_mrr_model": best_model,
        "best_mrr": round(best_mrr, 4) if records else 0.0,
    }


def write_report(
    records: list[dict],
    path: Path = REPORT_PATH,
    *,
    baseline: str | None = None,
) -> dict:
    """Write ``{generated_at, summary, records}`` JSON; return the summary."""
    summary = aggregate(records, baseline=baseline)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return summary


def unknown_models(requested: list[str], available: list[str]) -> list[str]:
    """Return the requested model ids that aren't in *available*, preserving order.

    A tiny preflight so a typo'd or not-yet-registered embedder id gives a clear
    message before we start embedding, instead of a mid-run conductor 404.
    """
    have = set(available)
    seen: set[str] = set()
    missing: list[str] = []
    for m in requested:
        if m not in have and m not in seen:
            missing.append(m)
            seen.add(m)
    return missing


def load_queries(path: Path = QUERIES_PATH) -> list[dict]:
    """Load the gold query set (``{queries: [{query, relevant_slugs}]}``).

    A missing file returns ``[]`` — the harness still runs in label-free
    *agreement-only* mode (retrieval metrics report ``n_scored: 0``).
    """
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("queries", [])


# --------------------------------------------------------------------------- #
# Live seam (conductor) + CLI — owner-gated; embeds with each candidate model
# --------------------------------------------------------------------------- #

def _truncate_for_embed(body: str) -> str:
    text = clean_text(body or "")
    words = text.split()
    if len(words) > _MAX_WORDS_PER_ARTICLE:
        text = " ".join(words[:_MAX_WORDS_PER_ARTICLE])
    return text


def _corpus_from_articles(articles: list[dict]) -> list[dict]:
    return [
        {"slug": a.get("slug"), "text": _truncate_for_embed(a.get("body", ""))}
        for a in articles
    ]


def _live_embed(base_url: str = CONDUCTOR_BASE_URL, batch_size: int = 16):
    """Embed seam backed by the conductor's ``/v1/embeddings`` endpoint.

    The ``model_id`` is passed straight through so the conductor routes directly
    to that embedder (bypassing smart-routing), exactly like
    ``semantic_search._embed_batch`` but parameterised on the model.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - env guard
        raise ImportError(
            "openai package not installed. Run: pip install -e '.[analyze]'"
        ) from exc
    client = OpenAI(base_url=base_url, api_key="local")

    def embed(model_id: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            resp = client.embeddings.create(model=model_id, input=chunk)
            items = sorted(resp.data, key=lambda d: d.index)
            vectors.extend(item.embedding for item in items)
        return vectors

    return embed


def _available_model_ids(base_url: str = CONDUCTOR_BASE_URL) -> list[str]:
    """Best-effort list of model ids the conductor exposes (empty on any error)."""
    try:
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key="local")
        return [m.id for m in client.models.list().data]
    except Exception:  # pragma: no cover - network/env guard; preflight is optional
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.embedding_compare",
        description="Compare candidate embedding models against the pinned "
                    "sbert-mpnet-v2 (decision D2) before ever swapping it. "
                    "Owner-gated: a live pass embeds the corpus with each "
                    "candidate model via the conductor, so it refuses to run if "
                    "the conductor is down.",
    )
    parser.add_argument(
        "--models", nargs="+", metavar="MODEL",
        help="candidate embedder ids to compare (the baseline is added "
             "automatically if absent)",
    )
    parser.add_argument(
        "--baseline", default=BASELINE_MODEL,
        help=f"pinned model every candidate is measured against (default: {BASELINE_MODEL})",
    )
    parser.add_argument("--queries", type=Path, default=QUERIES_PATH,
                        help="gold query set (default: eval/embedding_queries.json); "
                             "absent → agreement-only mode")
    parser.add_argument("--output", type=Path, default=REPORT_PATH,
                        help="report path (default: data/analysis/embedding_compare.json)")
    parser.add_argument("--ks", type=int, nargs="+", default=list(DEFAULT_KS),
                        help="k values for precision/recall/overlap (default: 1 3 5)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the corpus to N articles this run (faster smoke test)")
    args = parser.parse_args(argv)

    model_ids = list(args.models or [])
    if args.baseline not in model_ids:
        model_ids.insert(0, args.baseline)
    if len(model_ids) < 2:
        print("Give at least one --models candidate to compare against the baseline.")
        return 1

    if not require_conductor(base_url=CONDUCTOR_BASE_URL):
        return 2

    # Preflight the model ids so a typo / not-yet-registered embedder fails clearly
    # here rather than as a mid-run conductor 404. Skipped if listing is unavailable.
    available = _available_model_ids()
    if available:
        missing = unknown_models(model_ids, available)
        if missing:
            print(
                f"Unknown embedder id(s): {', '.join(missing)}. "
                "Register them in the conductor's models.yaml (or fix the spelling) "
                "before comparing. Available: " + ", ".join(sorted(available))
            )
            return 1

    articles = load_articles()
    if args.limit is not None:
        articles = articles[: args.limit]
    corpus = _corpus_from_articles(articles)
    if not corpus:
        print("No articles to embed. Run `make scrape` first.")
        return 1

    queries = load_queries(args.queries)
    records = compare_models(
        model_ids,
        corpus,
        queries,
        _live_embed(),
        baseline=args.baseline,
        ks=tuple(args.ks),
        log=lambda m: print(m, flush=True),
    )
    summary = write_report(records, args.output, baseline=args.baseline)
    print(
        f"\nEmbedding comparison ({summary['n_models']} models, "
        f"{len(queries)} gold queries, {len(corpus)} articles): "
        f"best MRR = {summary['best_mrr_model']} ({summary['best_mrr']:.3f}).\n"
        f"Report → {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
