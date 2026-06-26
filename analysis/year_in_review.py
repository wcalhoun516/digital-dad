"""Year in Review — an annual digest email from the archive.

Roadmap #23 (family): once a year, look back over everything Dr. Calhoun published in a
given calendar year and assemble a single keepsake email — how much he wrote, the themes
that dominated, and a handful of his most notable calls — in the same Georgia-serif voice
as the weekly "On This Day" note.

This module is deliberately **deterministic and offline**: it reads the analysis outputs
already on disk (`themes.json`, `predictions.json`) and the corpus, and renders an email to
``data/cron/emails/``. It makes no conductor, network, or LLM calls, so it is safe to run
unattended. Delivery stays human-in-the-loop via the existing Gmail-MCP draft path (D9).
"""

import html
from collections import Counter

# Conviction ordering for ranking notable predictions (most → least committed). Anything
# outside this list sorts last, so an unexpected confidence label can't outrank a real one.
_CONVICTION_RANK = {"certain": 0, "confident": 1, "hedged": 2}


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


def notable_predictions(predictions: list[dict], year, limit: int = 6) -> list[dict]:
    """Pick a year's most notable predictions, most-committed first.

    Filters ``predictions`` (from ``predictions.json``) to those whose ``article_date`` falls
    in ``year``, ranks by conviction (certain > confident > hedged > other), dedupes identical
    claims, and returns at most ``limit``. Deterministic: ties keep first-seen order.
    """
    y = str(year)
    in_year = [p for p in predictions if (p.get("article_date") or "")[:4] == y]
    ranked = sorted(
        in_year,
        key=lambda p: _CONVICTION_RANK.get(p.get("confidence_language"), len(_CONVICTION_RANK)),
    )
    out: list[dict] = []
    seen: set[str] = set()
    for p in ranked:
        claim = p.get("claim", "")
        if claim in seen:
            continue
        seen.add(claim)
        out.append(p)
        if len(out) >= limit:
            break
    return out


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
      <p style="font-size: 0.8em; color: #888; margin: 0;">{confidence} &middot; <a href="{url}" style="color: #c9a84c; text-decoration: none;">{title}</a></p>
    </div>"""

_PREDICTIONS_SECTION = """\
  <h2 style="font-size: 1.2em; font-weight: 400; margin: 24px 0 8px;">Notable calls</h2>
{items}"""


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


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
                confidence=_esc((p.get("confidence_language") or "").title() or "Prediction"),
                title=_esc(p.get("article_title", "")),
                url=html.escape(p.get("article_url", "#"), quote=True),
            )
            for p in preds
        )
        predictions_section = _PREDICTIONS_SECTION.format(items=items)
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
        for p in preds:
            conf = (p.get("confidence_language") or "").title() or "Prediction"
            lines.append(f"- [{conf}] {p.get('claim', '')} — {p.get('article_title', '')}")
    return "\n".join(lines)
