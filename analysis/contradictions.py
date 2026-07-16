"""Contradiction / mind-change finder (roadmap #15) — *where did he revise a view?*

Reads the entity list already on disk (`data/analysis/entities.json`) plus the corpus bodies,
tracks Dad's **stance toward each subject over time**, and emits
`data/analysis/contradictions.json`: the subjects (people/orgs) whose sentiment *reversed sign*
between his earlier and later writing, each with the representative early/late quotes. It's a
companion to `entity_graph.py` (#14) and `calhoun_isms.py` (#16) — the data layer a dashboard
tab could later render.

Deliberately **deterministic and offline**: no conductor, network, or LLM calls, so it is safe
to run unattended. "Stance" here is a heuristic, not a judgment: each sentence that names a
subject is scored by a small, transparent polarity lexicon (positive words minus negative
words, matched on word boundaries). A subject is flagged as a "mind change" when the *mean*
stance of the earlier half of its mentions and the later half have **opposite signs** and the
gap clears a threshold. This is intentionally simple — it does not model negation ("not
strong") or sarcasm, so the output is a set of *candidates* for a human to read, not a verdict.
The artifact carries public slugs, dates, and short excerpts of already-published article text.
"""

import argparse
import re
from statistics import mean

from .calhoun_isms import split_sentences
from .utils import ANALYSIS_DIR, clean_text, load_articles, save_analysis

# Transparent polarity lexicon. Tuned for Dad's markets/policy commentary voice: words that
# signal approval vs. alarm about a subject. Matched on word boundaries (see `stance_score`).
_POSITIVE = frozenset({
    "strong", "success", "successful", "wise", "smart", "brilliant", "impressive",
    "robust", "healthy", "promising", "credible", "sound", "admirable", "visionary",
    "effective", "prudent", "resilient", "genius", "triumph", "boom", "recovery",
    "confidence", "confident", "optimistic", "right", "correct", "win", "gains",
    "opportunity", "attractive", "undervalued", "bullish",
})
_NEGATIVE = frozenset({
    "weak", "failure", "failed", "wrong", "mistake", "reckless", "dangerous",
    "crisis", "collapse", "disaster", "catastrophic", "catastrophe", "bubble",
    "fraud", "incompetent", "folly", "doomed", "risky", "losses", "decline",
    "threat", "panic", "misguided", "flawed", "overvalued", "delusion", "bearish",
    "trouble", "troubled", "danger", "fear", "broken", "worthless", "bust",
})

# Author byline + photo-credit boilerplate that `entities.py` surfaces as "entities" but that
# aren't subjects Dad writes *about*. Mirrors `entity_graph.py`'s exclude posture. Overridable.
_DEFAULT_EXCLUDE = frozenset({
    "George Calhoun", "Calhoun", "Rafael", "Stevens", "Getty Images", "AFP", "Photo",
})

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def stance_score(sentence: str) -> int:
    """Net polarity of a sentence: (# positive words) − (# negative words).

    Transparent and deterministic. Words are matched on boundaries (so "strongman" does not
    count as "strong"). No negation/sarcasm handling — this is a coarse signal by design.
    """
    words = [w.lower() for w in _WORD_RE.findall(sentence)]
    pos = sum(1 for w in words if w in _POSITIVE)
    neg = sum(1 for w in words if w in _NEGATIVE)
    return pos - neg


def mentions(sentence: str, entity: str) -> bool:
    """True if ``entity`` appears in ``sentence`` as a whole word/phrase (case-insensitive)."""
    if not entity:
        return False
    return re.search(rf"\b{re.escape(entity)}\b", sentence, flags=re.IGNORECASE) is not None


def split_observations(observations: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a (date-sorted) observation list into earlier/later halves.

    The midpoint goes to the *late* half on an odd count, so a subject with an odd number of
    mentions leans its pivot toward the later period.
    """
    mid = len(observations) // 2
    return observations[:mid], observations[mid:]


def _extreme(observations: list[dict], *, positive: bool) -> dict:
    """The single most stance-extreme observation (max if ``positive`` else min)."""
    return max(observations, key=lambda o: o["stance"] if positive else -o["stance"])


def detect_reversal(
    observations: list[dict],
    *,
    min_observations: int = 4,
    min_delta: float = 1.0,
) -> dict | None:
    """Flag a stance reversal in one subject's time-ordered stance observations.

    Returns a reversal dict when the earlier half's mean stance and the later half's mean stance
    have **opposite signs** and ``|late_mean − early_mean| ≥ min_delta``; otherwise ``None``.
    Requires at least ``min_observations`` observations. Pure/deterministic.
    """
    if len(observations) < min_observations:
        return None

    ordered = sorted(observations, key=lambda o: o.get("date", ""))
    early, late = split_observations(ordered)
    if not early or not late:
        return None

    early_mean = mean(o["stance"] for o in early)
    late_mean = mean(o["stance"] for o in late)

    opposite_signs = (early_mean > 0 > late_mean) or (early_mean < 0 < late_mean)
    if not opposite_signs:
        return None
    if abs(late_mean - early_mean) < min_delta:
        return None

    early_positive = early_mean > 0
    return {
        "early_stance": round(early_mean, 3),
        "late_stance": round(late_mean, 3),
        "delta": round(late_mean - early_mean, 3),
        "direction": "cooled" if early_positive else "warmed",
        "n_observations": len(ordered),
        "early_quote": _quote(_extreme(early, positive=early_positive)),
        "late_quote": _quote(_extreme(late, positive=not early_positive)),
    }


def _quote(observation: dict) -> dict:
    return {
        "sentence": observation.get("sentence", ""),
        "date": observation.get("date", ""),
        "slug": observation.get("slug", ""),
        "title": observation.get("title", ""),
        "stance": observation.get("stance", 0),
    }


def _target_entities(
    entities_data: dict,
    *,
    min_mentions: int,
    exclude: frozenset[str],
) -> list[tuple[str, str]]:
    """(name, type) targets from entities.json, above the mention floor and not excluded."""
    targets: list[tuple[str, str]] = []
    for key, etype in (("top_people", "person"), ("top_organizations", "organization")):
        for ent in entities_data.get(key, []):
            name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
            count = ent.get("article_count", ent.get("count", 0)) if isinstance(ent, dict) else 0
            if not name or name in exclude:
                continue
            if count < min_mentions:
                continue
            targets.append((name, etype))
    return targets


def _stance_observations(articles: list[dict], entity: str) -> list[dict]:
    """Every sentence that names ``entity`` and carries a nonzero stance, with its metadata."""
    observations: list[dict] = []
    for article in articles:
        text = clean_text(article.get("body", ""))
        if not text or entity.lower() not in text.lower():
            continue
        for sentence in split_sentences(text):
            if not mentions(sentence, entity):
                continue
            score = stance_score(sentence)
            if score == 0:
                continue
            observations.append({
                "date": article.get("date", ""),
                "slug": article.get("slug", ""),
                "title": article.get("title", ""),
                "sentence": sentence,
                "stance": score,
            })
    return observations


def find_contradictions(
    articles: list[dict],
    entities_data: dict,
    *,
    min_observations: int = 4,
    min_mentions: int = 4,
    min_delta: float = 1.0,
    exclude: frozenset[str] | None = None,
) -> dict:
    """Build the mind-change board (pure; no I/O).

    For each frequent subject in ``entities_data`` (people/orgs with ``article_count ≥
    min_mentions``, minus the boilerplate ``exclude`` set), collect its stance observations
    across the corpus and test for a sign-reversal (:func:`detect_reversal`). Flagged subjects
    are returned sorted by the magnitude of the swing (largest first). Fully deterministic.
    """
    exclude = _DEFAULT_EXCLUDE if exclude is None else exclude
    targets = _target_entities(entities_data, min_mentions=min_mentions, exclude=exclude)

    contradictions: list[dict] = []
    scanned = 0
    for name, etype in targets:
        scanned += 1
        observations = _stance_observations(articles, name)
        reversal = detect_reversal(
            observations, min_observations=min_observations, min_delta=min_delta
        )
        if reversal is None:
            continue
        contradictions.append({"entity": name, "type": etype, **reversal})

    contradictions.sort(key=lambda r: (-abs(r["delta"]), r["entity"]))

    return {
        "meta": {
            "num_contradictions": len(contradictions),
            "candidates_scanned": scanned,
            "params": {
                "min_observations": min_observations,
                "min_mentions": min_mentions,
                "min_delta": min_delta,
            },
        },
        "contradictions": contradictions,
    }


def render_markdown(result: dict) -> str:
    """A short human-readable summary (for `--dry-run` and logs)."""
    meta = result["meta"]
    lines = [
        "# Mind changes / contradictions",
        "",
        f"{meta['num_contradictions']} subjects flipped stance "
        f"(of {meta['candidates_scanned']} scanned).",
    ]
    for r in result.get("contradictions", []):
        lines += [
            "",
            f"## {r['entity']} ({r['type']}) — {r['direction']} "
            f"[{r['early_stance']} → {r['late_stance']}, Δ{r['delta']}]",
            f"- early ({r['early_quote']['date']}): “{r['early_quote']['sentence']}”",
            f"- late  ({r['late_quote']['date']}): “{r['late_quote']['sentence']}”",
        ]
    return "\n".join(lines)


def run(
    articles: list[dict] | None = None,
    *,
    entities_data: dict | None = None,
    min_observations: int = 4,
    min_mentions: int = 4,
    min_delta: float = 1.0,
    exclude: frozenset[str] | None = None,
    write: bool = True,
) -> dict:
    """Build the mind-change board and (unless ``write=False``) write `contradictions.json`.

    Deterministic and offline: reads the corpus (or the injected ``articles``) and
    `entities.json` (or the injected ``entities_data``). Makes no conductor/network/LLM calls.
    """
    if articles is None:
        articles = load_articles()
    if entities_data is None:
        entities_data = _load_entities()

    result = find_contradictions(
        articles,
        entities_data,
        min_observations=min_observations,
        min_mentions=min_mentions,
        min_delta=min_delta,
        exclude=exclude,
    )

    if write:
        save_analysis("contradictions.json", result)

    return result


def _load_entities() -> dict:
    import json

    path = ANALYSIS_DIR / "entities.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No entity analysis at {path}. Run `make analyze entities` first."
        )
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Contradiction / mind-change finder (roadmap #15)."
    )
    parser.add_argument("--min-observations", type=int, default=4,
                        help="Minimum stance-bearing mentions before a subject is testable "
                             "(default 4).")
    parser.add_argument("--min-mentions", type=int, default=4,
                        help="Only consider subjects appearing in ≥ N articles (default 4).")
    parser.add_argument("--min-delta", type=float, default=1.0,
                        help="Minimum early→late mean-stance swing to flag (default 1.0).")
    parser.add_argument("--no-exclude", action="store_true",
                        help="Keep author/photo boilerplate subjects (off by default).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the summary without writing contradictions.json.")
    args = parser.parse_args(argv)

    result = run(
        min_observations=args.min_observations,
        min_mentions=args.min_mentions,
        min_delta=args.min_delta,
        exclude=frozenset() if args.no_exclude else None,
        write=not args.dry_run,
    )
    print(render_markdown(result))
    if args.dry_run:
        print("\nDry run — nothing written.")
    else:
        print(f"\nWrote {ANALYSIS_DIR / 'contradictions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
