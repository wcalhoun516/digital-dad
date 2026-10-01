"""positions: what he held to be true, grouped by subject, with his record (roadmap #43).

The archive can retrieve **articles** (On This Day) and **passages** (Ask Dad). Nothing
retrieved **positions** — ``predictions.json`` holds ~600 dated, adjudicated claims, but spread
across ~400 free-text topic strings ("Fed policy", "Fed policy errors", "monetary policy"...),
so "what did he say about the Fed, and how did it go?" had no answer. This module groups those
claims into subjects and writes ``data/analysis/positions.json``: one record per subject with
its claims, date span and won/lost record. It is the unit the weekly column (#44–#46) selects
from, and it is reusable by Ask Dad and the year-in-review digest.

Design, per the approved 2026-09-07 spec, with three choices worth knowing:

**The clustering unit is the canonical topic, not the claim.** ``entity_aliases.canonicalize``
folds the cheap variants first ("The Fed" / "Fed" → "Federal Reserve"), and every claim filed
under one topic lands in one subject. Clustering claims individually would scatter a topic
across subjects and make ``aliases`` a lie.

**Each topic is embedded as topic + its claims, blended.** Measured, not guessed, on the real
corpus against hand-labelled same/different topic pairs (``eval/positions_pairs.json``,
sbert-mpnet-v2, 2026-10-01): the topic string alone merges "Tesla valuation" with "Alibaba
valuation" (the shared word wins); the claims alone drag "stock market" into "Fed policy" (he
discusses them together). The normalized sum of the two is the only variant that got every
pair right.

**Average linkage, at 0.50.** Single linkage chains A≈B≈C into one blob; average linkage asks
whether two groups are alike *on the whole*. The threshold is the conservative edge of the
range that scores every labelled pair. On the first 22 pairs that range was 0.50-0.60, so 0.60
was taken; ten pairs added *afterwards, unseen*, broke it ("Ant Group IPO" / "Ant Group
regulation" split), and only 0.45-0.50 survive all 32. Subjects at 0.50 are topic *areas*
(oil and natural gas are one "energy" subject; inflation includes deflation) rather than
narrow claims. Re-measure with ``make positions ARGS=--sweep`` whenever the label set or the
embedder changes — there is no held-out set left, so new labels are the next check.

Verdicts resolve through ``adjudicate.effective_verdict``, so a ruling from ``make adjudicate``
outranks the advisory LLM verdict here exactly as it does on the Track Record tab.

The embedder is an injected seam (``embed``) so the grouping is tested offline against fixed
vectors; the live one is the pinned ``sbert-mpnet-v2`` via the conductor (D2). Nothing here is
specific to one author — any ``predictions.json`` produces an index.
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .adjudicate import VALID_VERDICTS, effective_source, effective_verdict
from .entity_aliases import canonicalize
from .utils import DATA_DIR, log, save_analysis

DEFAULT_THRESHOLD = 0.50
PREDICTIONS_PATH = DATA_DIR / "analysis" / "predictions.json"
OUTPUT_NAME = "positions.json"
# Hand-labelled topic pairs the threshold is measured against (text-free, committed).
PAIRS_PATH = Path(__file__).resolve().parent.parent / "eval" / "positions_pairs.json"

Embed = Callable[[list[str]], Sequence[Sequence[float]]]


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def cluster(vectors: Sequence[Sequence[float]], threshold: float) -> list[list[int]]:
    """Average-linkage agglomerative clustering on cosine similarity.

    Repeatedly merges the two groups with the highest *mean* pairwise similarity, while that
    mean is ``>= threshold``. Returns member indices, each group sorted, groups ordered by
    their first member — deterministic for a given input.
    """
    n = len(vectors)
    if n == 0:
        return []
    unit = _unit(np.asarray(vectors, dtype=float))
    # sums[a, b] = sum of pairwise similarities between groups a and b; merging folds rows and
    # columns together, so each merge costs O(n) instead of recomputing every pair.
    sums = unit @ unit.T
    size = np.ones(n)
    alive = np.ones(n, dtype=bool)
    members = {i: [i] for i in range(n)}

    while alive.sum() > 1:
        mean = sums / np.outer(size, size)
        mean[~alive, :] = -np.inf
        mean[:, ~alive] = -np.inf
        np.fill_diagonal(mean, -np.inf)
        a, b = np.unravel_index(np.argmax(mean), mean.shape)
        # A small tolerance so a pair at exactly the threshold is not lost to float error.
        if mean[a, b] < threshold - 1e-9:
            break
        a, b = min(a, b), max(a, b)
        sums[a, :] += sums[b, :]
        sums[:, a] += sums[:, b]
        size[a] += size[b]
        alive[b] = False
        members[a] += members.pop(b)

    return sorted((sorted(group) for group in members.values()), key=lambda g: g[0])


def _date(prediction: dict) -> str:
    return prediction.get("prediction_date") or prediction.get("article_date") or ""


def _claim(prediction: dict) -> dict:
    return {
        "claim": prediction.get("claim", ""),
        "date": _date(prediction),
        "slug": prediction.get("article_slug", ""),
        "title": prediction.get("article_title", ""),
        "url": prediction.get("article_url", ""),
        "confidence_language": prediction.get("confidence_language", ""),
        "verdict": effective_verdict(prediction),
        "verdict_source": effective_source(prediction),
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "subject"


def _group_by_topic(predictions: list[dict]) -> dict[str, dict]:
    """Group predictions by canonical topic key, keeping the most-used display spelling."""
    topics: dict[str, dict] = {}
    for p in predictions:
        name = canonicalize(p.get("topic") or "")
        if not name:
            continue
        entry = topics.setdefault(name.casefold(), {"spellings": Counter(), "predictions": []})
        entry["spellings"][name] += 1
        entry["predictions"].append(p)
    for entry in topics.values():
        # Most common spelling; ties to the alphabetically first so output never depends on
        # input order.
        entry["name"] = min(entry["spellings"], key=lambda s: (-entry["spellings"][s], s))
    return topics


def _topic_vectors(topics: list[dict], embed: Embed) -> np.ndarray:
    """Blend each topic's own embedding with the mean embedding of its claims (see module doc)."""
    names = [t["name"] for t in topics]
    claim_texts = [f"{t['name']}: {p.get('claim', '')}" for t in topics for p in t["predictions"]]
    vectors = np.asarray(embed(names + claim_texts), dtype=float)
    topic_vecs = _unit(vectors[: len(names)])
    claim_vecs = _unit(vectors[len(names) :])

    blended = []
    start = 0
    for topic, own in zip(topics, topic_vecs):
        count = len(topic["predictions"])
        claims_mean = _unit(claim_vecs[start : start + count].mean(axis=0, keepdims=True))[0]
        blended.append(own + claims_mean)
        start += count
    return _unit(np.asarray(blended))


def _subject(topics: list[dict]) -> dict:
    # Deepest topic first; ties alphabetical (case-insensitive) so names are stable.
    topics = sorted(topics, key=lambda t: (-len(t["predictions"]), t["name"].casefold()))
    claims = sorted(
        (_claim(p) for t in topics for p in t["predictions"]),
        key=lambda c: (c["date"], c["slug"], c["claim"]),
    )
    record = {verdict: 0 for verdict in VALID_VERDICTS}
    for c in claims:
        record[c["verdict"]] = record.get(c["verdict"], 0) + 1
    dates = [c["date"] for c in claims if c["date"]]
    return {
        "subject": topics[0]["name"],
        "aliases": [t["name"] for t in topics],
        "claims": claims,
        "span": [min(dates), max(dates)] if dates else [None, None],
        "record": record,
    }


def _prepare(predictions: list[dict], embed: Embed) -> tuple[list[dict], np.ndarray]:
    """Group by topic and embed once, so several thresholds can be tried on one embedding."""
    topics = sorted(_group_by_topic(predictions).values(), key=lambda t: t["name"].casefold())
    if not topics:
        return [], np.empty((0, 0))
    return topics, _topic_vectors(topics, embed)


def _assemble(topics: list[dict], vectors: np.ndarray, threshold: float) -> list[dict]:
    groups = cluster(vectors, threshold)
    subjects = [_subject([topics[i] for i in group]) for group in groups]
    subjects.sort(key=lambda s: (-len(s["claims"]), s["subject"].casefold()))

    used: Counter = Counter()
    for s in subjects:
        base = _slug(s["subject"])
        used[base] += 1
        s["id"] = f"pos:{base}" if used[base] == 1 else f"pos:{base}-{used[base]}"
    # Lead each record with its id, matching the spec's record shape.
    return [{"id": s.pop("id"), **s} for s in subjects]


def build_positions(
    predictions: list[dict], *, embed: Embed, threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    """Group predictions into subjects, deepest first. Blank-topic predictions are left out."""
    return _assemble(*_prepare(predictions, embed), threshold)


# ---------------------------------------------------------------------------
# Calibration — the threshold is a measured choice, so the measurement is re-runnable.
# ---------------------------------------------------------------------------


def load_pairs(path: Path = PAIRS_PATH) -> dict:
    """Load hand-labelled ``{"same": [[a, b]], "different": [[a, b]]}`` topic pairs.

    A missing file loads empty, so the module still builds without a label set.
    """
    path = Path(path)
    if not path.exists():
        return {"same": [], "different": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"same": data.get("same", []), "different": data.get("different", [])}


def _topic_key(topic: str) -> str:
    return canonicalize(topic).casefold()


def score_pairs(subjects: list[dict], pairs: dict) -> dict:
    """Score a grouping against labelled pairs.

    A pair naming a topic no subject carries is listed under ``missing`` and not scored: a
    label that rotted when the topics were re-extracted must not count as a pass.
    """
    subject_of = {_topic_key(alias): s["id"] for s in subjects for alias in s["aliases"]}
    score: dict = {"missing": []}
    for kind, want_same in (("same", True), ("different", False)):
        tally = {"ok": 0, "total": 0, "failed": []}
        for a, b in pairs.get(kind, []):
            ids = subject_of.get(_topic_key(a)), subject_of.get(_topic_key(b))
            if None in ids:
                score["missing"].append([a, b])
                continue
            tally["total"] += 1
            if (ids[0] == ids[1]) == want_same:
                tally["ok"] += 1
            else:
                tally["failed"].append([a, b])
        score[kind] = tally
    return score


def sweep(
    predictions: list[dict], *, embed: Embed, thresholds: Sequence[float], pairs: dict
) -> list[dict]:
    """Score each threshold against the labelled pairs, embedding only once."""
    topics, vectors = _prepare(predictions, embed)
    rows = []
    for threshold in thresholds:
        subjects = _assemble(topics, vectors, threshold)
        score = score_pairs(subjects, pairs)
        rows.append(
            {
                "threshold": threshold,
                "num_subjects": len(subjects),
                "same_ok": score["same"]["ok"],
                "same_total": score["same"]["total"],
                "different_ok": score["different"]["ok"],
                "different_total": score["different"]["total"],
                "failed": score["same"]["failed"] + score["different"]["failed"],
                "missing": score["missing"],
            }
        )
    return rows


def build_document(
    predictions: list[dict],
    *,
    embed: Embed,
    embed_model: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    subjects = build_positions(predictions, embed=embed, threshold=threshold)
    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "source": "predictions.json",
            "embed_model": embed_model,
            "threshold": threshold,
            "num_predictions": len(predictions),
            "untopiced": sum(1 for p in predictions if not canonicalize(p.get("topic") or "")),
            "num_topics": sum(len(s["aliases"]) for s in subjects),
            "num_subjects": len(subjects),
        },
        "subjects": subjects,
    }


def _live_embed(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """The pinned sbert-mpnet-v2 via the conductor, batched."""
    from .semantic_search import _embed_batch

    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        log.debug("Embedding %d-%d of %d", start, start + batch_size, len(texts))
        out.extend(_embed_batch(texts[start : start + batch_size]))
    return out


def run(
    *,
    predictions_path: Path = PREDICTIONS_PATH,
    embed: Embed | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    write: bool = True,
) -> dict:
    """Build the positions index from ``predictions.json`` and (unless ``write=False``) save it."""
    from .semantic_search import EMBED_MODEL

    if not predictions_path.exists():
        raise FileNotFoundError(
            f"No predictions at {predictions_path}. Run `make analyze predictions` first."
        )
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))["predictions"]

    doc = build_document(
        predictions,
        embed=embed or _live_embed,
        embed_model=EMBED_MODEL,
        threshold=threshold,
    )
    log.info(
        "Positions: %d claims across %d topics grouped into %d subjects (threshold %.2f)",
        doc["meta"]["num_predictions"] - doc["meta"]["untopiced"],
        doc["meta"]["num_topics"],
        doc["meta"]["num_subjects"],
        threshold,
    )
    if doc["meta"]["untopiced"]:
        log.warning("%d prediction(s) have no topic and were left out", doc["meta"]["untopiced"])
    if write:
        path = save_analysis(OUTPUT_NAME, doc)
        log.info("positions saved to %s", path)
    return doc


def render_summary(doc: dict, top: int = 15) -> str:
    lines = [
        f"{doc['meta']['num_subjects']} subjects from {doc['meta']['num_topics']} topics "
        f"(threshold {doc['meta']['threshold']:.2f})",
        "",
    ]
    for s in doc["subjects"][:top]:
        r = s["record"]
        lines.append(
            f"{len(s['claims']):4d}  {s['subject']:<40.40}  "
            f"{r['vindicated']}V {r['mixed']}M {r['wrong']}W {r['unfalsifiable']}U "
            f"{r['pending']}P  {s['span'][0]}..{s['span'][1]}"
        )
    return "\n".join(lines)


def render_sweep(rows: list[dict]) -> str:
    lines = ["threshold  subjects  same     different  failed pairs"]
    for r in rows:
        lines.append(
            f"{r['threshold']:9.2f}  {r['num_subjects']:8d}  "
            f"{r['same_ok']:2d}/{r['same_total']:<2d}    {r['different_ok']:2d}/{r['different_total']:<2d}"
            f"      {'; '.join(' ~ '.join(p) for p in r['failed'])}"
        )
    if rows and rows[0]["missing"]:
        lines.append(f"\nUnscored (topic not found): {rows[0]['missing']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Positions index (roadmap #43): group predictions into subjects."
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="Average-linkage cosine threshold for merging topics "
                             f"(default {DEFAULT_THRESHOLD}).")
    parser.add_argument("--top", type=int, default=15,
                        help="How many subjects to list in the summary (default 15).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the summary without writing positions.json.")
    parser.add_argument("--sweep", action="store_true",
                        help="Score thresholds 0.40-0.80 against eval/positions_pairs.json and "
                             "print the table; writes nothing.")
    args = parser.parse_args(argv)

    if args.sweep:
        predictions = json.loads(PREDICTIONS_PATH.read_text(encoding="utf-8"))["predictions"]
        thresholds = [round(0.40 + 0.05 * i, 2) for i in range(9)]
        rows = sweep(predictions, embed=_live_embed, thresholds=thresholds, pairs=load_pairs())
        print(render_sweep(rows))
        return 0

    doc = run(threshold=args.threshold, write=not args.dry_run)
    print(render_summary(doc, top=args.top))
    print("\nDry run — nothing written." if args.dry_run else f"\nWrote {OUTPUT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
