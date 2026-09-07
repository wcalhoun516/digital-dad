"""Year in Review — an annual digest email from the archive.

Roadmap #23 (family): once a year, look back over everything Dr. Calhoun published in a
given calendar year and assemble a single keepsake email — how much he wrote, the themes
that dominated, and a handful of his most notable calls — in the same Georgia-serif voice
as the weekly "On This Day" note.

The "notable calls" are ranked by how they were **adjudicated** (see
:func:`analysis.adjudicate.effective_verdict`) before how confidently they were stated, and
every call is rendered with its verdict alongside the year's full won/lost record. Ranking on
conviction alone let a claim the archive had already judged *wrong* headline the email purely
because he had stated it with certainty.

This module is deliberately **deterministic and offline**: it reads the analysis outputs
already on disk (`themes.json`, `predictions.json`) and the corpus, and renders an email to
``data/cron/emails/``. It makes no conductor, network, or LLM calls, so it is safe to run
unattended. Delivery stays human-in-the-loop via the existing Gmail-MCP draft path (D9).
"""

import argparse
import datetime
import html
import json
from collections import Counter
from pathlib import Path

from .adjudicate import effective_verdict
from .utils import ANALYSIS_DIR, DATA_DIR

EMAIL_DIR = DATA_DIR / "cron" / "emails"
THEMES_PATH = ANALYSIS_DIR / "themes.json"
PREDICTIONS_PATH = ANALYSIS_DIR / "predictions.json"

# Conviction ordering for ranking notable predictions (most → least committed). Anything
# outside this list sorts last, so an unexpected confidence label can't outrank a real one.
_CONVICTION_RANK = {"certain": 0, "confident": 1, "hedged": 2}

# How the year *scored*, which outranks how loudly it was said. "unfalsifiable" and "pending"
# sort below every adjudicated call: the first was never a testable call, the second has not
# been ruled on yet, so neither belongs above a claim that actually came good (or didn't).
_VERDICT_RANK = {"vindicated": 0, "mixed": 1, "wrong": 2, "unfalsifiable": 3, "pending": 4}

# Verdicts that represent a call the archive has actually ruled on, for the year's scoreboard.
ADJUDICATED_VERDICTS = ("vindicated", "mixed", "wrong")


def articles_for_year(theme_articles: list[dict], year) -> list[dict]:
    """Return the theme-tagged article records published in ``year``.

    ``theme_articles`` is the ``articles`` list from ``themes.json`` (each ``{slug, title,
    date, word_count, cluster_label, ...}``). Entries with an empty/missing date are
    dropped, so the corpus's author-listing page (no date) never counts.
    """
    y = str(year)
    return [a for a in theme_articles if (a.get("date") or "")[:4] == y]


def top_themes(year_articles: list[dict], top_n: int = 5) -> list[dict]:
    """Rank the themes for a year's articles by article count.

    Returns ``[{label, count}]`` sorted by count desc, ties broken alphabetically by label.
    """
    counts = Counter(a.get("cluster_label", "") for a in year_articles)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"label": label, "count": n} for label, n in ranked[:top_n]]


def notable_predictions(
    predictions: list[dict], year, limit: int = 6, *, max_per_article: int = 1
) -> list[dict]:
    """Pick a year's most notable predictions, best-adjudicated first.

    Filters ``predictions`` (from ``predictions.json``) to those whose ``article_date`` falls
    in ``year``, ranks by **effective verdict** (vindicated > mixed > wrong > unfalsifiable >
    pending) and then by conviction (certain > confident > hedged) within a verdict, dedupes
    identical claims, and returns at most ``limit``. Deterministic: ties keep first-seen order.

    The verdict leads the ranking because a keepsake that headlines a claim the archive has
    already judged *wrong* — purely because he stated it confidently — misrepresents the year.
    Verdicts resolve through :func:`analysis.adjudicate.effective_verdict`, so a human ruling
    outranks the advisory LLM one. Losing calls are ranked down, not hidden; the renderers
    label every verdict.

    ``max_per_article`` caps how many calls a single article can contribute (default 1) so the
    digest spans his year rather than over-quoting one prolific piece.
    """
    y = str(year)
    in_year = [p for p in predictions if (p.get("article_date") or "")[:4] == y]
    ranked = sorted(
        in_year,
        key=lambda p: (
            _VERDICT_RANK.get(effective_verdict(p), len(_VERDICT_RANK)),
            _CONVICTION_RANK.get(p.get("confidence_language"), len(_CONVICTION_RANK)),
        ),
    )
    out: list[dict] = []
    seen: set[str] = set()
    per_article: Counter = Counter()
    for p in ranked:
        claim = p.get("claim", "")
        if claim in seen:
            continue
        article_key = p.get("article_slug") or p.get("article_title", "")
        if article_key and per_article[article_key] >= max_per_article:
            continue
        seen.add(claim)
        per_article[article_key] += 1
        out.append(p)
        if len(out) >= limit:
            break
    return out


def verdict_tally(predictions: list[dict], year) -> dict:
    """Tally how a year's *adjudicated* calls actually turned out.

    Counts every prediction from ``year`` the archive has ruled on — not merely the handful
    the digest shows — so the keepsake can state the year's real record. Unfalsifiable and
    not-yet-judged claims are excluded: neither is a call that was won or lost.
    """
    y = str(year)
    counts = {v: 0 for v in ADJUDICATED_VERDICTS}
    for p in predictions:
        if (p.get("article_date") or "")[:4] != y:
            continue
        verdict = effective_verdict(p)
        if verdict in counts:
            counts[verdict] += 1
    counts["total"] = sum(counts.values())
    return counts


def build_digest(
    theme_articles: list[dict],
    predictions: list[dict],
    year,
    *,
    top_themes_n: int = 5,
    predictions_n: int = 6,
) -> dict:
    """Assemble the full year-in-review digest for ``year`` (pure; no I/O)."""
    year_articles = articles_for_year(theme_articles, year)
    return {
        "year": int(year),
        "article_count": len(year_articles),
        "total_words": sum(a.get("word_count", 0) for a in year_articles),
        "top_themes": top_themes(year_articles, top_n=top_themes_n),
        "notable_predictions": notable_predictions(predictions, year, limit=predictions_n),
        "verdict_tally": verdict_tally(predictions, year),
    }


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #2a2a2a; line-height: 1.7;">
  <div style="border-bottom: 2px solid #c9a84c; padding-bottom: 12px; margin-bottom: 24px;">
    <h1 style="font-size: 1.4em; font-weight: 400; margin: 0;">{year} — A Year in the Archive</h1>
    <p style="font-size: 0.85em; color: #888; margin: 4px 0 0;">The writing of Dr. George Calhoun</p>
  </div>

  <p style="font-size: 1.05em;">In {year}, he published <strong>{article_count}</strong> {article_noun} — about <strong>{total_words:,}</strong> words.</p>

  {themes_section}

  {predictions_section}

  <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 0.8em; color: #aaa; text-align: center;">
    Digital Dad &middot; The Intellectual Archive of Dr. George Calhoun
  </div>
</body>
</html>
"""

_THEME_ITEM = '    <li style="margin-bottom: 4px;"><strong>{label}</strong> &mdash; {count} {noun}</li>'

_THEMES_SECTION = """\
  <h2 style="font-size: 1.2em; font-weight: 400; margin: 24px 0 8px;">The themes that dominated</h2>
  <ul style="padding-left: 20px; margin: 0 0 8px;">
{items}
  </ul>"""

_PREDICTION_ITEM = """\
    <div style="margin-bottom: 16px;">
      <p style="font-size: 0.98em; margin: 0 0 4px;">&ldquo;{claim}&rdquo;</p>
      <p style="font-size: 0.8em; color: #888; margin: 0;"><strong style="color: {verdict_color};">{verdict}</strong> &middot; {confidence} &middot; <a href="{url}" style="color: #c9a84c; text-decoration: none;">{title}</a></p>
    </div>"""

_PREDICTIONS_SECTION = """\
  <h2 style="font-size: 1.2em; font-weight: 400; margin: 24px 0 8px;">Notable calls</h2>
{scoreboard}{items}"""

_SCOREBOARD = """\
  <p style="font-size: 0.9em; color: #666; margin: 0 0 12px; font-style: italic;">{sentence}</p>
"""

# How a verdict is named in the email. "pending" is spelled out — a family reader should not
# have to guess that it means "we haven't ruled on this yet" rather than "he was wrong".
_VERDICT_LABEL = {
    "vindicated": "Vindicated",
    "mixed": "Mixed",
    "wrong": "Wrong",
    "unfalsifiable": "Unfalsifiable",
    "pending": "Not yet judged",
}

# Muted enough for a keepsake, dark enough to read on the white email background (the
# dashboard's brighter palette is tuned for its dark theme).
_VERDICT_COLOR = {
    "vindicated": "#4a7c59",
    "mixed": "#8a6d3b",
    "wrong": "#a04a4a",
}

_TALLY_PHRASE = {
    "vindicated": "{n} came good",
    "mixed": "{n} landed partly",
    "wrong": "{n} went the other way",
}


def _join_clauses(clauses: list[str]) -> str:
    """Join phrases as prose: "a", "a and b", "a, b and c"."""
    if len(clauses) <= 1:
        return "".join(clauses)
    return f"{', '.join(clauses[:-1])} and {clauses[-1]}"


def scoreboard_sentence(tally: dict, year) -> str:
    """One honest line about the year's adjudicated record, or "" if nothing was ruled on."""
    total = tally.get("total", 0)
    if not total:
        return ""
    clauses = [
        _TALLY_PHRASE[v].format(n=tally[v]) for v in ADJUDICATED_VERDICTS if tally.get(v)
    ]
    noun = "call" if total == 1 else "calls"
    return (
        f"Of the {total} {noun} from {year} the archive has since ruled on, "
        f"{_join_clauses(clauses)}."
    )


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _verdict_label(prediction: dict) -> str:
    verdict = effective_verdict(prediction)
    return _VERDICT_LABEL.get(verdict, verdict.title())


def render_html(digest: dict) -> str:
    """Render the digest as a Georgia-serif HTML email body. All user text is escaped."""
    year = digest["year"]
    count = digest["article_count"]

    themes = digest.get("top_themes") or []
    if themes:
        items = "\n".join(
            _THEME_ITEM.format(
                label=_esc(t["label"]),
                count=t["count"],
                noun="article" if t["count"] == 1 else "articles",
            )
            for t in themes
        )
        themes_section = _THEMES_SECTION.format(items=items)
    else:
        themes_section = ""

    preds = digest.get("notable_predictions") or []
    if preds:
        items = "\n".join(
            _PREDICTION_ITEM.format(
                claim=_esc(p.get("claim", "")),
                verdict=_esc(_verdict_label(p)),
                verdict_color=_VERDICT_COLOR.get(effective_verdict(p), "#999"),
                confidence=_esc((p.get("confidence_language") or "").title() or "Prediction"),
                title=_esc(p.get("article_title", "")),
                url=html.escape(p.get("article_url", "#"), quote=True),
            )
            for p in preds
        )
        sentence = scoreboard_sentence(digest.get("verdict_tally") or {}, year)
        scoreboard = _SCOREBOARD.format(sentence=_esc(sentence)) if sentence else ""
        predictions_section = _PREDICTIONS_SECTION.format(scoreboard=scoreboard, items=items)
    else:
        predictions_section = ""

    return _HTML_TEMPLATE.format(
        year=year,
        article_count=count,
        article_noun="article" if count == 1 else "articles",
        total_words=digest.get("total_words", 0),
        themes_section=themes_section,
        predictions_section=predictions_section,
    )


def render_markdown(digest: dict) -> str:
    """Render the digest as a plain-text/markdown summary (for logs + dry-run preview)."""
    year = digest["year"]
    count = digest["article_count"]
    lines = [
        f"# {year} — A Year in the Archive",
        "",
        f"{count} article{'' if count == 1 else 's'}, ~{digest.get('total_words', 0):,} words.",
    ]
    themes = digest.get("top_themes") or []
    if themes:
        lines += ["", "## Themes that dominated"]
        lines += [f"- {t['label']} ({t['count']})" for t in themes]
    preds = digest.get("notable_predictions") or []
    if preds:
        lines += ["", "## Notable calls"]
        sentence = scoreboard_sentence(digest.get("verdict_tally") or {}, year)
        if sentence:
            lines += [sentence, ""]
        for p in preds:
            conf = (p.get("confidence_language") or "").title() or "Prediction"
            lines.append(
                f"- [{_verdict_label(p)} · {conf}] {p.get('claim', '')}"
                f" — {p.get('article_title', '')}"
            )
    return "\n".join(lines)


def default_year(today: datetime.date | None = None) -> int:
    """The latest *complete* calendar year (this year minus one)."""
    today = today or datetime.date.today()
    return today.year - 1


def _load_json(path: Path, default):
    """Load JSON from ``path``; return ``default`` if it is missing or malformed."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _load_theme_articles() -> list[dict]:
    data = _load_json(THEMES_PATH, {})
    return data.get("articles", []) if isinstance(data, dict) else []


def _load_predictions() -> list[dict]:
    data = _load_json(PREDICTIONS_PATH, {})
    return data.get("predictions", []) if isinstance(data, dict) else []


def run(
    year: int | None = None,
    *,
    theme_articles: list[dict] | None = None,
    predictions: list[dict] | None = None,
    email_dir: Path = EMAIL_DIR,
    write: bool = True,
) -> dict:
    """Build the year-in-review digest and (unless ``write=False``) render it to disk.

    Deterministic and offline: reads ``themes.json`` + ``predictions.json`` (or the injected
    lists) and writes an HTML email to ``email_dir``. Makes no conductor/network/LLM calls.
    Delivery stays human-in-the-loop via the Gmail-MCP draft path (D9).
    """
    if year is None:
        year = default_year()
    if theme_articles is None:
        theme_articles = _load_theme_articles()
    if predictions is None:
        predictions = _load_predictions()

    digest = build_digest(theme_articles, predictions, year)
    html_body = render_html(digest)
    markdown = render_markdown(digest)
    subject = f"{year} — A Year in the Archive"

    email_file = None
    if write:
        email_dir = Path(email_dir)
        email_dir.mkdir(parents=True, exist_ok=True)
        email_file = email_dir / f"year_in_review_{year}.html"
        email_file.write_text(html_body)

    return {
        "year": year,
        "subject": subject,
        "article_count": digest["article_count"],
        "total_words": digest["total_words"],
        "html_body": html_body,
        "markdown": markdown,
        "email_file": str(email_file) if email_file else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Year-in-review digest email (roadmap #23).")
    parser.add_argument(
        "--year", type=int, default=None,
        help="Calendar year to review (default: the latest complete year).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the digest summary without writing the email to disk.",
    )
    args = parser.parse_args(argv)

    result = run(args.year, write=not args.dry_run)
    print(result["markdown"])
    if result["email_file"]:
        print(f"\nEmail saved: {result['email_file']}")
    else:
        print("\nDry run — nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
