"""Calhoun-isms — the most quotable/aphoristic sentences per theme (roadmap #16).

Reads the theme assignments already on disk (`data/analysis/themes.json`) plus the corpus
bodies, scores every sentence for "quotability" with transparent heuristics, and emits
`data/analysis/calhoun_isms.json`: the strongest aphorisms grouped by theme, plus an overall
board. It's a companion to `entity_graph.py` (#14) — the data layer a dashboard tab could later
render.

Deliberately **deterministic and offline**: no conductor, network, or LLM calls, so it is safe
to run unattended. "Quotable" here is a heuristic, not a judgment: a sentence scores well when
it is self-contained (stands alone without an antecedent), sits in a memorable length band, and
carries aphoristic signals — a definitional claim (`X is …`), a generalizing absolute
(`always`, `never`, `no one`), or a contrast (`not … but …`) — while newsy specifics (dates,
percentages, attributions like "Powell said") pull the score down. The output carries public
slugs, dates, and short excerpts of already-published article text.
"""

import argparse
import re

from .utils import ANALYSIS_DIR, clean_text, load_articles, save_analysis

# Sentence openers that lean on an antecedent — a sentence starting with one of these rarely
# stands alone as an aphorism, so it's dropped by the quotability gate. Matched on the first
# word, case-sensitively (a mid-sentence "This" is fine; a leading one is not).
_DEPENDENT_OPENERS = frozenset({
    "But", "And", "So", "Yet", "Or", "Nor", "Thus", "Then", "Also",
    "This", "That", "These", "Those", "It", "They", "Them", "Their", "Its",
    "He", "She", "His", "Her", "Here", "There",
    "However", "Therefore", "Moreover", "Furthermore", "Meanwhile", "Instead",
    "Which", "Who", "Because",
})

# Aphoristic signal words: absolutes / generalizations that make a line feel like a maxim.
_APHORISTIC_MARKERS = frozenset({
    "always", "never", "every", "everyone", "everything", "no one", "nobody",
    "nothing", "none", "only", "must", "cannot", "inevitable", "inevitably",
    "ultimately", "fundamental", "fundamentally", "essence", "essential",
    "truth", "real", "reality", "simply", "matter", "sooner or later",
    "in the end", "at its core", "the point",
})

# Attribution / reporting markers: a quote we can attribute to someone else, or plain
# news reportage, is not one of *his* aphorisms.
_ATTRIBUTION_MARKERS = ("said", "says", "according to", "told", "wrote", "argued", "noted")

_URL_MARKERS = ("http", "www.", "@", ".com", ".org")

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def split_sentences(text: str) -> list[str]:
    """Split cleaned text into sentences.

    Splits on sentence-ending punctuation (``.!?``) followed by whitespace. ``text`` is expected
    to already be whitespace-normalized (via :func:`analysis.utils.clean_text`). Abbreviations
    like "U.S." can over-split, but such fragments are filtered out later by the quotability
    gate, so the simple rule is good enough.
    """
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _words(sentence: str) -> list[str]:
    return _WORD_RE.findall(sentence)


def is_quotable(sentence: str, *, min_words: int = 8, max_words: int = 30) -> bool:
    """Gate a sentence as a candidate aphorism (before scoring).

    A candidate must: be a declarative statement (end with ``.`` or ``!``, not a question),
    sit in the ``[min_words, max_words]`` band, start with a capital letter, not open with a
    dependent word (:data:`_DEPENDENT_OPENERS`), and carry no URL/handle noise.
    """
    sentence = sentence.strip()
    if not sentence or sentence[-1] not in ".!":
        return False

    words = _words(sentence)
    if not (min_words <= len(words) <= max_words):
        return False

    if not sentence[0].isupper():
        return False

    if words[0] in _DEPENDENT_OPENERS:
        return False

    low = sentence.lower()
    if any(marker in low for marker in _URL_MARKERS):
        return False

    return True


def quotability_score(sentence: str) -> float:
    """A deterministic 0-ish..N quotability score. Higher = more aphoristic.

    Transparent additive heuristic (no model): a length term peaking around a memorable
    ~14-word line, plus bonuses for aphoristic markers, a definitional ``X is/are …`` claim, and
    a contrast (``not``/``but``); minus penalties for attribution and newsy digits.
    """
    low = " " + sentence.lower() + " "
    words = _words(sentence)
    n = len(words)

    # Length term: peaks at ~14 words, tapering either side (0.0..1.0).
    length_term = max(0.0, 1.0 - abs(n - 14) / 14.0)
    score = length_term

    # Aphoristic markers (absolutes / generalizations), matched on word/phrase boundaries.
    score += sum(1.0 for m in _APHORISTIC_MARKERS if f" {m} " in low)

    # Definitional claim.
    if " is " in low or " are " in low:
        score += 0.75

    # Contrast structure.
    if " not " in low or " but " in low or " rather than " in low:
        score += 0.5

    # Penalties.
    score -= sum(1.5 for m in _ATTRIBUTION_MARKERS if f" {m} " in low)
    if re.search(r"\d", sentence):
        score -= 0.75

    return round(score, 4)


def _theme_by_slug(themes_data: dict) -> dict[str, dict]:
    """Map article slug -> {"cluster_id", "label"} from a themes.json payload."""
    labels = {c["id"]: c.get("label", "") for c in themes_data.get("clusters", [])}
    out: dict[str, dict] = {}
    for art in themes_data.get("articles", []):
        slug = art.get("slug")
        if not slug:
            continue
        cid = art.get("cluster_id")
        out[slug] = {
            "cluster_id": cid,
            "label": labels.get(cid) or art.get("cluster_label", "") or f"Theme {cid}",
        }
    return out


def extract_isms(
    articles: list[dict],
    themes_data: dict,
    *,
    top_n: int = 10,
    min_words: int = 8,
    max_words: int = 30,
) -> dict:
    """Build the per-theme Calhoun-isms (pure; no I/O).

    For each corpus article that has a theme assignment, split its cleaned body into sentences,
    keep the quotable ones, and score them. Group by theme, dedupe identical sentences (keeping
    the highest score), sort by score, and cap each theme at ``top_n``. Also returns an
    ``overall_top`` board across all themes. Fully deterministic.
    """
    theme_of = _theme_by_slug(themes_data)

    # theme label -> {"cluster_id", "candidates": {text: ism_dict}}
    buckets: dict[str, dict] = {}
    used_articles = 0

    for article in articles:
        slug = article.get("slug")
        theme = theme_of.get(slug)
        if theme is None:
            continue
        used_articles += 1
        label = theme["label"]
        bucket = buckets.setdefault(
            label, {"cluster_id": theme["cluster_id"], "candidates": {}}
        )

        text = clean_text(article.get("body", ""))
        for sentence in split_sentences(text):
            if not is_quotable(sentence, min_words=min_words, max_words=max_words):
                continue
            score = quotability_score(sentence)
            existing = bucket["candidates"].get(sentence)
            if existing is not None and existing["score"] >= score:
                continue
            bucket["candidates"][sentence] = {
                "text": sentence,
                "score": score,
                "slug": slug,
                "title": article.get("title", ""),
                "date": article.get("date", ""),
                "word_count": len(_words(sentence)),
            }

    themes = []
    overall: list[dict] = []
    for label, bucket in buckets.items():
        ranked = sorted(
            bucket["candidates"].values(),
            key=lambda i: (-i["score"], i["text"]),
        )
        top = ranked[:top_n]
        themes.append({
            "theme": label,
            "cluster_id": bucket["cluster_id"],
            "candidate_count": len(ranked),
            "isms": top,
        })
        for ism in top:
            overall.append({**ism, "theme": label})

    themes.sort(key=lambda t: (t["cluster_id"] if t["cluster_id"] is not None else 1e9, t["theme"]))
    overall.sort(key=lambda i: (-i["score"], i["text"]))

    return {
        "meta": {
            "total_articles": used_articles,
            "num_themes": len(themes),
            "params": {"top_n": top_n, "min_words": min_words, "max_words": max_words},
        },
        "themes": themes,
        "overall_top": overall[:top_n],
    }


def render_markdown(result: dict) -> str:
    """A short human-readable summary (for `--dry-run` and logs)."""
    meta = result["meta"]
    lines = [
        "# Calhoun-isms",
        "",
        f"{meta['num_themes']} themes, from {meta['total_articles']} articles "
        f"(top {meta['params']['top_n']} per theme).",
    ]
    overall = result.get("overall_top") or []
    if overall:
        lines += ["", "## Most quotable overall"]
        lines += [f"- “{i['text']}”  — {i['theme']} ({i['date']})" for i in overall[:10]]
    for theme in result.get("themes", []):
        lines += ["", f"## {theme['theme']}"]
        for ism in theme["isms"][:5]:
            lines.append(f"- “{ism['text']}”  ({ism['date']})")
    return "\n".join(lines)


def run(
    articles: list[dict] | None = None,
    *,
    themes_data: dict | None = None,
    top_n: int = 10,
    min_words: int = 8,
    max_words: int = 30,
    write: bool = True,
) -> dict:
    """Build the Calhoun-isms and (unless ``write=False``) write `calhoun_isms.json`.

    Deterministic and offline: reads the corpus (or the injected ``articles``) and
    `themes.json` (or the injected ``themes_data``). Makes no conductor/network/LLM calls.
    """
    if articles is None:
        articles = load_articles()
    if themes_data is None:
        themes_data = _load_themes()

    result = extract_isms(
        articles, themes_data, top_n=top_n, min_words=min_words, max_words=max_words
    )

    if write:
        save_analysis("calhoun_isms.json", result)

    return result


def _load_themes() -> dict:
    import json

    path = ANALYSIS_DIR / "themes.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No theme analysis at {path}. Run `make analyze themes` first."
        )
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calhoun-isms — most quotable sentences per theme (roadmap #16)."
    )
    parser.add_argument("--top", type=int, default=10,
                        help="Keep the N highest-scoring aphorisms per theme (default 10).")
    parser.add_argument("--min-words", type=int, default=8,
                        help="Minimum sentence length in words (default 8).")
    parser.add_argument("--max-words", type=int, default=30,
                        help="Maximum sentence length in words (default 30).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the summary without writing calhoun_isms.json.")
    args = parser.parse_args(argv)

    result = run(
        top_n=args.top,
        min_words=args.min_words,
        max_words=args.max_words,
        write=not args.dry_run,
    )
    print(render_markdown(result))
    if args.dry_run:
        print("\nDry run — nothing written.")
    else:
        print(f"\nWrote {ANALYSIS_DIR / 'calhoun_isms.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
