"""Per-entity stance over time — how his tone toward a person/org shifts by year (roadmap #17).

Reads the entity extraction already on disk (`data/analysis/entities.json`) plus the corpus
bodies, and for each major entity tracks a **stance trajectory**: the mean tone of the sentences
that mention it, aggregated per year. It's a companion to `entity_graph.py` (#14) — this module
ships the deterministic builder; a dashboard "stance over time" viz is a later slice.

Deliberately **deterministic and offline**: no conductor, network, or LLM calls, so it is safe
to run unattended. The nltk/VADER path used elsewhere is unavailable in this environment, so
stance here is a **transparent heuristic**: a small, hand-curated polarity lexicon scores each
sentence (positive terms minus negative terms, with a light negation flip), and an entity's
stance in an article is the mean polarity of the sentences that name it. This is a proxy for
tone, not a claim of ground-truth sentiment — it is meant to surface *trends*, not verdicts.

The output (`entity_stance.json`) carries only public entity names, numeric stance scores,
counts, and years — **no article-body text** — so it is committable exactly like
`entity_graph.json` (contrast `calhoun_isms.json`, which embeds sentences and is gitignored).
"""

import argparse
import re

from .entity_graph import _DEFAULT_EXCLUDE, _norm_exclude, article_entities, entity_id
from .utils import ANALYSIS_DIR, clean_text, load_articles, save_analysis

# Transparent polarity lexicon. Tone words common in his financial/political commentary; a
# sentence's polarity is (positive hits − negative hits), so the choice is deliberately small
# and legible rather than exhaustive. Matched on lowercased word tokens (see `_TOKEN_RE`).
_POSITIVE = frozenset({
    "success", "successful", "succeed", "strong", "strength", "gain", "gains", "gained",
    "win", "wins", "won", "growth", "grow", "growing", "boom", "booming", "innovative",
    "innovation", "brilliant", "resilient", "robust", "opportunity", "promising", "impressive",
    "sound", "healthy", "confidence", "confident", "triumph", "achievement", "prudent", "wise",
    "credible", "stable", "stability", "recovery", "thrive", "thrives", "thriving", "praise",
    "remarkable", "outstanding", "effective", "efficient", "breakthrough", "vindicated",
})
_NEGATIVE = frozenset({
    "failure", "fail", "fails", "failed", "failing", "weak", "weakness", "loss", "losses",
    "lose", "losing", "crisis", "collapse", "disaster", "disastrous", "risk", "risky",
    "danger", "dangerous", "threat", "threaten", "fraud", "fraudulent", "corruption", "corrupt",
    "reckless", "bubble", "crash", "decline", "declining", "worst", "damage", "flawed",
    "flaw", "dubious", "trouble", "troubled", "mistake", "misguided", "illusion", "problematic",
    "unsustainable", "doomed", "panic", "fear", "fears", "scandal", "chaos", "broken",
    "stagnant", "stagnation", "overvalued", "delusion", "folly", "hubris",
})
# A polarity hit is flipped when one of these appears within the preceding `_NEG_WINDOW` tokens.
_NEGATORS = frozenset({"not", "no", "never", "without", "hardly", "barely", "nor", "n't", "cannot"})
_NEG_WINDOW = 3

_TOKEN_RE = re.compile(r"[a-z][a-z']*")

# Beyond `entity_graph`'s boilerplate set, the extractor also surfaces bare image-credit words
# ("Photo", "Photographer", "Illustration") that are page furniture, not subjects Dr. Calhoun
# takes a stance toward. Folded into the default exclude here (stance-scoped, so `entity_graph`'s
# committed artifact is untouched). Matched case-insensitively.
_EXTRA_EXCLUDE = frozenset({"photo", "photographer", "photos", "illustration", "image"})


def _resolve_exclude(exclude) -> frozenset[str]:
    """Default (``None``) → `entity_graph`'s boilerplate set plus the stance-scoped extras;
    an explicit collection is used verbatim (lowercased)."""
    if exclude is None:
        return _DEFAULT_EXCLUDE | _EXTRA_EXCLUDE
    return _norm_exclude(exclude)


def sentence_polarity(sentence: str) -> int:
    """Signed tone of one sentence via the transparent polarity lexicon.

    Returns ``(#positive − #negative)`` over the sentence's word tokens, where a polarity word
    is **flipped** if a negator (:data:`_NEGATORS`) occurs within the preceding
    :data:`_NEG_WINDOW` tokens. Case-insensitive; no model, no network. 0 means neutral (or a
    balance of positive and negative cues).
    """
    tokens = _TOKEN_RE.findall(sentence.lower())
    score = 0
    for i, tok in enumerate(tokens):
        if tok in _POSITIVE:
            sign = 1
        elif tok in _NEGATIVE:
            sign = -1
        else:
            continue
        window = tokens[max(0, i - _NEG_WINDOW):i]
        if any(w in _NEGATORS for w in window):
            sign = -sign
        score += sign
    return score


def split_sentences(text: str) -> list[str]:
    """Split cleaned text into sentences (same simple rule as `calhoun_isms.split_sentences`)."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def entity_mentioned(sentence: str, name: str) -> bool:
    """True if ``name`` occurs in ``sentence`` as a whole word (case-insensitive).

    Word boundaries stop ``"Fed"`` from matching inside ``"federal"``; internal spaces in a
    multi-word name are matched literally, so ``"Federal Reserve"`` matches regardless of case.
    """
    name = name.strip()
    if not name:
        return False
    pattern = r"\b" + re.escape(name) + r"\b"
    return re.search(pattern, sentence, flags=re.IGNORECASE) is not None


def mentioning_sentences(text: str, name: str) -> list[str]:
    """The sentences of ``text`` that name ``name`` (see :func:`entity_mentioned`)."""
    return [s for s in split_sentences(text) if entity_mentioned(s, name)]


def article_stance(body: str, name: str) -> dict:
    """Mean polarity of the sentences in ``body`` that mention ``name``.

    Returns ``{"mean_stance": float | None, "n_sentences": int, "n_positive": int,
    "n_negative": int}``. ``mean_stance`` is ``None`` when the entity is not mentioned (so a
    caller can distinguish "no signal" from "neutral"). Pure and deterministic.
    """
    sentences = mentioning_sentences(clean_text(body), name)
    if not sentences:
        return {"mean_stance": None, "n_sentences": 0, "n_positive": 0, "n_negative": 0}
    scores = [sentence_polarity(s) for s in sentences]
    return {
        "mean_stance": round(sum(scores) / len(scores), 4),
        "n_sentences": len(sentences),
        "n_positive": sum(1 for s in scores if s > 0),
        "n_negative": sum(1 for s in scores if s < 0),
    }


def classify_trend(trajectory: list[dict], *, threshold: float = 0.25) -> tuple[str, float]:
    """Label an entity's stance drift as ``warming`` / ``cooling`` / ``steady``.

    Compares the mean stance of the **last** dated year to the **first** across ``trajectory``
    (each point ``{year, mean_stance, ...}``). ``trend_delta = last − first``; a magnitude below
    ``threshold`` (or fewer than two years of signal) is ``steady``. Deterministic.
    """
    points = sorted((p for p in trajectory if p.get("mean_stance") is not None),
                    key=lambda p: p["year"])
    if len(points) < 2:
        return "steady", 0.0
    delta = round(points[-1]["mean_stance"] - points[0]["mean_stance"], 4)
    if delta >= threshold:
        return "warming", delta
    if delta <= -threshold:
        return "cooling", delta
    return "steady", delta


def build_stance(
    articles: list[dict],
    entities_data: dict,
    *,
    top_n: int = 30,
    min_articles: int = 2,
    min_mentions: int = 1,
    threshold: float = 0.25,
    exclude=None,
) -> dict:
    """Assemble per-entity yearly stance trajectories (pure; no I/O).

    Joins ``entities_data``'s ``per_article`` records (which entities appear in which article,
    plus its date) to the corpus ``articles`` (bodies, keyed by slug). For every entity in an
    article it scores the sentences that name it (:func:`article_stance`) and accumulates the raw
    polarity **sum** and sentence **count** per calendar year — so yearly means are exact, not
    means-of-means. Keeps entities mentioned in at least ``min_articles`` articles, ranks by
    article_count, caps at ``top_n``, and labels each entity's trend. ``exclude`` drops
    boilerplate (defaults to `entity_graph`'s set). Fully deterministic.
    """
    body_by_slug = {a.get("slug"): a for a in articles}
    resolved_exclude = _resolve_exclude(exclude)

    # id -> {id, name, type, article_slugs: set, by_year: {year: [sum, n_sentences, {slugs}]}}
    acc: dict[str, dict] = {}

    for record in entities_data.get("per_article", []):
        slug = record.get("slug")
        article = body_by_slug.get(slug)
        if article is None:
            continue
        year = (record.get("date") or article.get("date") or "")[:4]
        if not year:
            continue
        body = article.get("body", "")
        # aliases=False: this module searches the body for each entity's *surface* name
        # (mentioning_sentences below), so canonicalizing here would miss variant mentions
        # ("Fed" vs "the Federal Reserve"). Alias-aware stance is a separate slice.
        for name, entity_type in article_entities(
            record, min_mentions=min_mentions, exclude=resolved_exclude, aliases=False
        ):
            sentences = mentioning_sentences(clean_text(body), name)
            if not sentences:
                continue
            scores = [sentence_polarity(s) for s in sentences]
            nid = entity_id(name, entity_type)
            node = acc.setdefault(nid, {
                "id": nid, "name": name, "type": entity_type,
                "article_slugs": set(), "by_year": {},
            })
            node["article_slugs"].add(slug)
            bucket = node["by_year"].setdefault(year, [0, 0, set()])
            bucket[0] += sum(scores)
            bucket[1] += len(scores)
            bucket[2].add(slug)

    entities = []
    for node in acc.values():
        if len(node["article_slugs"]) < min_articles:
            continue
        trajectory = []
        total_sum = total_n = 0
        for year in sorted(node["by_year"]):
            s, n, slugs = node["by_year"][year]
            total_sum += s
            total_n += n
            trajectory.append({
                "year": year,
                "mean_stance": round(s / n, 4) if n else None,
                "n_sentences": n,
                "n_articles": len(slugs),
            })
        trend, trend_delta = classify_trend(trajectory, threshold=threshold)
        entities.append({
            "id": node["id"],
            "name": node["name"],
            "type": node["type"],
            "article_count": len(node["article_slugs"]),
            "total_sentences": total_n,
            "overall_stance": round(total_sum / total_n, 4) if total_n else None,
            "trend": trend,
            "trend_delta": trend_delta,
            "trajectory": trajectory,
        })

    entities.sort(key=lambda e: (-e["article_count"], -e["total_sentences"], e["id"]))
    entities = entities[:top_n]

    warming = sorted(
        (e for e in entities if e["trend"] == "warming"),
        key=lambda e: (-e["trend_delta"], e["id"]),
    )
    cooling = sorted(
        (e for e in entities if e["trend"] == "cooling"),
        key=lambda e: (e["trend_delta"], e["id"]),
    )

    def _board(items):
        return [{"name": e["name"], "type": e["type"], "trend_delta": e["trend_delta"],
                 "overall_stance": e["overall_stance"]} for e in items]

    return {
        "meta": {
            "total_articles": entities_data.get("total_articles_analyzed"),
            "n_entities": len(entities),
            "params": {
                "top_n": top_n,
                "min_articles": min_articles,
                "min_mentions": min_mentions,
                "threshold": threshold,
                "excluded": sorted(resolved_exclude),
            },
        },
        "entities": entities,
        "warming": _board(warming[:10]),
        "cooling": _board(cooling[:10]),
    }


def render_markdown(result: dict) -> str:
    """A short human-readable summary (for `--dry-run` and logs)."""
    meta = result["meta"]
    lines = [
        "# Per-entity stance over time",
        "",
        f"{meta['n_entities']} entities (from {meta.get('total_articles')} articles). "
        "Stance is a heuristic tone proxy, not ground truth.",
    ]
    for title, key in (("Warming (tone rising)", "warming"), ("Cooling (tone falling)", "cooling")):
        board = result.get(key) or []
        if board:
            lines += ["", f"## {title}"]
            lines += [f"- {e['name']} ({e['type']}) — Δ{e['trend_delta']:+.2f}, "
                      f"overall {e['overall_stance']:+.2f}" for e in board]
    entities = result.get("entities") or []
    if entities:
        lines += ["", "## Most-written-about"]
        for e in entities[:10]:
            span = e["trajectory"]
            years = f"{span[0]['year']}–{span[-1]['year']}" if span else "—"
            lines.append(
                f"- {e['name']} ({e['type']}) — {e['article_count']} articles, {years}, "
                f"{e['trend']} (Δ{e['trend_delta']:+.2f})"
            )
    return "\n".join(lines)


def _load_entities():
    import json

    path = ANALYSIS_DIR / "entities.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No entities analysis at {path}. Run `make analyze entities` first."
        )
    return json.loads(path.read_text())


def run(
    articles: list[dict] | None = None,
    *,
    entities_data: dict | None = None,
    top_n: int = 30,
    min_articles: int = 2,
    min_mentions: int = 1,
    threshold: float = 0.25,
    exclude=None,
    write: bool = True,
) -> dict:
    """Build the per-entity stance trajectories and (unless ``write=False``) write it to disk.

    Deterministic and offline: reads the corpus (or the injected ``articles``) and
    `entities.json` (or the injected ``entities_data``), writes `entity_stance.json`. Makes no
    conductor/network/LLM calls.
    """
    if articles is None:
        articles = load_articles()
    if entities_data is None:
        entities_data = _load_entities()

    result = build_stance(
        articles,
        entities_data,
        top_n=top_n,
        min_articles=min_articles,
        min_mentions=min_mentions,
        threshold=threshold,
        exclude=exclude,
    )

    if write:
        save_analysis("entity_stance.json", result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-entity stance over time builder (roadmap #17)."
    )
    parser.add_argument("--top", type=int, default=30,
                        help="Keep the N most-written-about entities (default 30).")
    parser.add_argument("--min-articles", type=int, default=2,
                        help="Minimum articles mentioning an entity to include it (default 2).")
    parser.add_argument("--min-mentions", type=int, default=1,
                        help="Minimum mentions for an entity to count in an article (default 1).")
    parser.add_argument("--threshold", type=float, default=0.25,
                        help="Min |Δstance| (first→last year) to call a trend warming/cooling "
                             "(default 0.25).")
    parser.add_argument("--exclude", action="append", metavar="NAME", default=None,
                        help="Extra entity name to drop (repeatable); adds to the default "
                             "boilerplate set.")
    parser.add_argument("--no-exclude", action="store_true",
                        help="Disable the default boilerplate exclude set (keep all entities).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the summary without writing entity_stance.json.")
    args = parser.parse_args(argv)

    if args.no_exclude:
        exclude: frozenset[str] | None = frozenset()
    elif args.exclude:
        exclude = _DEFAULT_EXCLUDE | _EXTRA_EXCLUDE | {name.lower() for name in args.exclude}
    else:
        exclude = None

    result = run(
        top_n=args.top,
        min_articles=args.min_articles,
        min_mentions=args.min_mentions,
        threshold=args.threshold,
        exclude=exclude,
        write=not args.dry_run,
    )
    print(render_markdown(result))
    if args.dry_run:
        print("\nDry run — nothing written.")
    else:
        print(f"\nWrote {ANALYSIS_DIR / 'entity_stance.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
