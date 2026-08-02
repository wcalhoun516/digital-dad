"""Anthology — a printable "best of" keepsake from the archive.

Roadmap #24 (family): assemble a clean, printable "best of" anthology of Dr. George
Calhoun's writing — his vindicated calls and a signature piece per dominant theme —
rendered as a print-optimized HTML document the family can print or "Save as PDF".

Deterministic and offline: reads the analysis outputs already on disk
(`predictions.json`, `themes.json`), makes no conductor/network/LLM calls, and so is
safe to run unattended. Binary PDF generation is deferred to a later slice (browser
"Print to PDF" is the interim path); this module produces the print-ready HTML.
"""

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from .utils import ANALYSIS_DIR

THEMES_PATH = ANALYSIS_DIR / "themes.json"
PREDICTIONS_PATH = ANALYSIS_DIR / "predictions.json"
OUT_DIR = ANALYSIS_DIR

# Conviction ordering for ranking best calls (most → least committed). Anything outside this
# list sorts last, so an unexpected confidence label can't outrank a real one.
_CONVICTION_RANK = {"certain": 0, "confident": 1, "hedged": 2}


def _dated(theme_articles: list[dict]) -> list[dict]:
    """Theme-tagged articles with a non-empty date (drops the undated author-listing page)."""
    return [a for a in theme_articles if (a.get("date") or "")]


def corpus_span(theme_articles: list[dict]) -> dict:
    """Summarize the dated corpus: earliest date, latest date, and article count.

    Undated records (e.g. the Forbes author-listing page) are excluded so they can't skew
    the span or the count.
    """
    dated = _dated(theme_articles)
    if not dated:
        return {"first_date": None, "last_date": None, "count": 0}
    dates = sorted(a["date"] for a in dated)
    return {"first_date": dates[0], "last_date": dates[-1], "count": len(dated)}


def best_calls(predictions: list[dict], limit: int = 8, *, max_per_article: int = 1) -> list[dict]:
    """Pick his most notable **vindicated** predictions, most-committed first.

    Filters ``predictions`` (from ``predictions.json``) to those whose ``llm_verdict`` is
    ``"vindicated"``, ranks by conviction (certain > confident > hedged > other), dedupes
    identical claims, caps how many a single article can contribute (``max_per_article``, so
    the anthology spans his work rather than over-quoting one piece), and returns at most
    ``limit``. Deterministic: ties keep first-seen order.
    """
    vindicated = [p for p in predictions if p.get("llm_verdict") == "vindicated"]
    ranked = sorted(
        vindicated,
        key=lambda p: _CONVICTION_RANK.get(p.get("confidence_language"), len(_CONVICTION_RANK)),
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


def _top_theme_labels(dated: list[dict], top_n: int) -> list[str]:
    """The ``top_n`` cluster labels by article count; ties break alphabetically."""
    counts = Counter(a.get("cluster_label", "") for a in dated)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [label for label, _ in ranked[:top_n]]


def _representative(articles: list[dict]) -> dict:
    """The signature article for a theme: most words, ties → earliest date, then slug."""
    return sorted(
        articles,
        key=lambda a: (-a.get("word_count", 0), a.get("date", ""), a.get("slug", "")),
    )[0]


def signature_pieces(theme_articles: list[dict], top_n: int = 5) -> list[dict]:
    """Choose one representative article for each of the ``top_n`` dominant themes.

    Themes are ranked by dated-article count (ties alphabetical); within a theme the
    representative is the longest piece (ties → earliest, then slug). Undated records are
    never eligible. Returns ``[{theme, count, article}]`` in theme-rank order.
    """
    dated = _dated(theme_articles)
    if not dated:
        return []
    by_theme: dict[str, list[dict]] = {}
    for a in dated:
        by_theme.setdefault(a.get("cluster_label", ""), []).append(a)
    out: list[dict] = []
    for label in _top_theme_labels(dated, top_n):
        members = by_theme[label]
        out.append({"theme": label, "count": len(members), "article": _representative(members)})
    return out


def reasoning_snippet(text: str | None, max_chars: int = 200) -> str:
    """A tight one-line gloss of a verdict's reasoning for the keepsake.

    Returns the first sentence if it fits in ``max_chars``; otherwise truncates at a word
    boundary and appends an ellipsis. Empty/None → "".
    """
    text = (text or "").strip()
    if not text:
        return ""
    first = text.split(". ", 1)[0].rstrip(".")
    first = f"{first}." if first else ""
    if len(first) <= max_chars:
        return first
    clipped = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;: ")
    return f"{clipped}…"


def build_anthology(
    theme_articles: list[dict],
    predictions: list[dict],
    *,
    calls_limit: int = 8,
    themes_n: int = 5,
) -> dict:
    """Assemble the full anthology structure (pure; no I/O)."""
    return {
        "span": corpus_span(theme_articles),
        "best_calls": best_calls(predictions, limit=calls_limit),
        "signature_pieces": signature_pieces(theme_articles, top_n=themes_n),
    }


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>The Best of Dr. George Calhoun</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 720px; margin: 0 auto; padding: 48px 32px;
    color: #2a2a2a; line-height: 1.7; }}
  h1 {{ font-size: 2em; font-weight: 400; margin: 0 0 4px; }}
  h2 {{ font-size: 1.3em; font-weight: 400; border-bottom: 2px solid #c9a84c;
    padding-bottom: 6px; margin: 8px 0 16px; }}
  .subtitle {{ color: #888; font-size: 0.95em; margin: 0 0 8px; }}
  .entry {{ margin-bottom: 20px; page-break-inside: avoid; }}
  .claim {{ font-size: 1.05em; margin: 0 0 4px; }}
  .meta {{ font-size: 0.82em; color: #888; margin: 0; }}
  .meta a {{ color: #c9a84c; text-decoration: none; }}
  .why {{ font-size: 0.85em; font-style: italic; color: #555; margin: 4px 0 0; }}
  section {{ page-break-before: always; }}
  section.frontispiece {{ page-break-before: avoid; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd;
    font-size: 0.8em; color: #aaa; text-align: center; }}
  @media print {{
    body {{ padding: 0; max-width: none; }}
    a {{ color: #2a2a2a; }}
    section {{ page-break-before: always; }}
    section.frontispiece {{ page-break-before: avoid; }}
  }}
</style>
</head>
<body>
  <section class="frontispiece">
    <h1>The Best of Dr. George Calhoun</h1>
    <p class="subtitle">A printable anthology from the intellectual archive</p>
    <p>{span_line}</p>
  </section>

  {best_calls_section}

  {signature_section}

  <footer>Digital Dad &middot; The Intellectual Archive of Dr. George Calhoun</footer>
</body>
</html>
"""

_CALL_ITEM = """\
    <div class="entry">
      <p class="claim">&ldquo;{claim}&rdquo;</p>
      <p class="meta">{confidence} &middot; <a href="{url}">{title}</a>{date}</p>{why}
    </div>"""

_WHY_LINE = '\n      <p class="why">Why it held up: {snippet}</p>'

_PIECE_ITEM = """\
    <div class="entry">
      <p class="claim"><a href="{url}" style="text-decoration:none;color:inherit;">{title}</a></p>
      <p class="meta">{theme}{date} &middot; {words:,} words</p>
    </div>"""


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _date_suffix(date: str) -> str:
    return f" &middot; {_esc(date)}" if date else ""


def _why_line(prediction: dict) -> str:
    snippet = reasoning_snippet(prediction.get("llm_verdict_reasoning"))
    return _WHY_LINE.format(snippet=_esc(snippet)) if snippet else ""


def render_html(anthology: dict) -> str:
    """Render the anthology as a print-ready Georgia-serif document. All user text escaped."""
    span = anthology.get("span") or {}
    count = span.get("count", 0)
    if count and span.get("first_date") and span.get("last_date"):
        span_line = (
            f"{count} article{'' if count == 1 else 's'}, "
            f"published {_esc(span['first_date'])} &ndash; {_esc(span['last_date'])}."
        )
    else:
        span_line = "An archive of his columns."

    calls = anthology.get("best_calls") or []
    if calls:
        items = "\n".join(
            _CALL_ITEM.format(
                claim=_esc(p.get("claim", "")),
                confidence=_esc((p.get("confidence_language") or "").title() or "Vindicated"),
                title=_esc(p.get("article_title", "")),
                url=html.escape(p.get("article_url", "#"), quote=True),
                date=_date_suffix(p.get("article_date", "")),
                why=_why_line(p),
            )
            for p in calls
        )
        best_calls_section = f'  <section>\n    <h2>His Best Calls</h2>\n{items}\n  </section>'
    else:
        best_calls_section = ""

    pieces = anthology.get("signature_pieces") or []
    if pieces:
        items = "\n".join(
            _PIECE_ITEM.format(
                title=_esc(s["article"].get("title", "")),
                url=html.escape(s["article"].get("url", "#"), quote=True),
                theme=_esc(s.get("theme", "")),
                date=_date_suffix(s["article"].get("date", "")),
                words=s["article"].get("word_count", 0),
            )
            for s in pieces
        )
        signature_section = f'  <section>\n    <h2>Signature Pieces</h2>\n{items}\n  </section>'
    else:
        signature_section = ""

    return _HTML_TEMPLATE.format(
        span_line=span_line,
        best_calls_section=best_calls_section,
        signature_section=signature_section,
    )


def render_markdown(anthology: dict) -> str:
    """Render the anthology as a plain-text/markdown summary (for logs + dry-run preview)."""
    span = anthology.get("span") or {}
    count = span.get("count", 0)
    lines = ["# The Best of Dr. George Calhoun", ""]
    if count and span.get("first_date"):
        lines.append(
            f"{count} article{'' if count == 1 else 's'}, "
            f"{span['first_date']} – {span['last_date']}."
        )
    calls = anthology.get("best_calls") or []
    if calls:
        lines += ["", "## His Best Calls"]
        for p in calls:
            conf = (p.get("confidence_language") or "").title() or "Vindicated"
            lines.append(f"- [{conf}] {p.get('claim', '')} — {p.get('article_title', '')}")
            snippet = reasoning_snippet(p.get("llm_verdict_reasoning"))
            if snippet:
                lines.append(f"    Why it held up: {snippet}")
    pieces = anthology.get("signature_pieces") or []
    if pieces:
        lines += ["", "## Signature Pieces"]
        for s in pieces:
            art = s["article"]
            lines.append(f"- {s.get('theme', '')}: {art.get('title', '')} ({art.get('date', '')})")
    return "\n".join(lines)


def _chromium_render(html_path: Path, pdf_path: Path) -> None:
    """Render ``html_path`` to ``pdf_path`` via headless Chromium (Playwright).

    Honors the template's ``@media print`` rules (page breaks, background gold rules) so the
    keepsake paginates properly. Kept as the default ``render_pdf`` seam so all orchestration
    stays offline-testable; this is the only part that needs a browser.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="Letter",
                print_background=True,
                margin={"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"},
            )
        finally:
            browser.close()


def render_pdf(html_path: Path, pdf_path: Path, *, render=None) -> Path:
    """Render the print-ready anthology HTML at ``html_path`` to a PDF at ``pdf_path``.

    Pure orchestration: validates the source exists, then delegates the actual rendering to
    the ``render(html_path, pdf_path)`` seam (defaulting to headless Chromium). Returns the
    written ``pdf_path``. Raises ``FileNotFoundError`` if the HTML is missing.
    """
    html_path = Path(html_path)
    pdf_path = Path(pdf_path)
    if not html_path.exists():
        raise FileNotFoundError(f"anthology HTML not found: {html_path}")
    (render or _chromium_render)(html_path, pdf_path)
    return pdf_path


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
    *,
    theme_articles: list[dict] | None = None,
    predictions: list[dict] | None = None,
    out_dir: Path = OUT_DIR,
    write: bool = True,
    calls_limit: int = 8,
    themes_n: int = 5,
    pdf: bool = False,
    pdf_render=None,
) -> dict:
    """Build the anthology and (unless ``write=False``) render it to disk.

    Deterministic and offline: reads ``themes.json`` + ``predictions.json`` (or the injected
    lists) and writes ``anthology.json`` (excerpt-level metadata, licensing-safe) plus a
    print-ready ``anthology.html`` to ``out_dir``. Makes no conductor/network/LLM calls.

    When ``pdf=True`` (and ``write=True``), also renders ``anthology.pdf`` from that HTML via
    ``render_pdf`` — the ``pdf_render`` seam defaults to headless Chromium. PDF rendering needs
    the HTML on disk, so it is skipped in dry-run (``write=False``).
    """
    if theme_articles is None:
        theme_articles = _load_theme_articles()
    if predictions is None:
        predictions = _load_predictions()

    anthology = build_anthology(
        theme_articles, predictions, calls_limit=calls_limit, themes_n=themes_n
    )
    html_body = render_html(anthology)
    markdown = render_markdown(anthology)

    json_file = html_file = pdf_file = None
    if write:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_file = out_dir / "anthology.json"
        json_file.write_text(json.dumps(anthology, indent=2, ensure_ascii=False) + "\n")
        html_file = out_dir / "anthology.html"
        html_file.write_text(html_body)
        if pdf:
            pdf_file = render_pdf(html_file, out_dir / "anthology.pdf", render=pdf_render)

    return {
        "anthology": anthology,
        "html_body": html_body,
        "markdown": markdown,
        "json_file": str(json_file) if json_file else None,
        "html_file": str(html_file) if html_file else None,
        "pdf_file": str(pdf_file) if pdf_file else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Printable best-of anthology (roadmap #24).")
    parser.add_argument(
        "--calls-limit", type=int, default=8,
        help="Maximum number of 'best calls' to include (default: 8).",
    )
    parser.add_argument(
        "--themes", type=int, default=5,
        help="Number of dominant themes to feature as signature pieces (default: 5).",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="Also render anthology.pdf from the HTML (headless Chromium; needs Playwright).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the anthology summary without writing anything to disk.",
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            write=not args.dry_run,
            calls_limit=args.calls_limit,
            themes_n=args.themes,
            pdf=args.pdf,
        )
    except Exception as exc:  # headless Chromium not installed / can't launch
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            print(f"SKIP PDF: headless Chromium unavailable ({msg.splitlines()[0]}).")
            print("The print-ready HTML is still the interim path — 'Print → Save as PDF'.")
            result = run(write=not args.dry_run, calls_limit=args.calls_limit, themes_n=args.themes)
        else:
            raise

    print(result["markdown"])
    if result["html_file"]:
        print(f"\nHTML saved:  {result['html_file']}")
        print(f"JSON saved:  {result['json_file']}")
        if result["pdf_file"]:
            print(f"PDF saved:   {result['pdf_file']}")
        else:
            print("Open the HTML in a browser and 'Print → Save as PDF' for a keepsake copy.")
    else:
        print("\nDry run — nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
