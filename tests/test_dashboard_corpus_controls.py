"""Behavioural tests for the Raw Corpus tab's search / filter / sort controls.

The tab promises "Every article, searchable and sortable" — the two halves have to
compose. Sorting by Title and then picking a year must keep the title order.

Two layers, mirroring `tests/test_dashboard_reading_room.py`:

  * **live** — the page is rendered from `dashboard/template.html` with a *synthetic*
    manifest (no real article text) and driven in headless Chromium. This is the only
    layer that proves behaviour rather than the presence of source strings. It SKIPs
    cleanly when Chromium can't launch, so CI (no browser) stays green.
  * **structural** — CI-safe string checks that pin the shape of the fix: the controls
    share one render path, and the header advertises the active sort.
"""

import json
from pathlib import Path

import pytest

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"
MANIFEST_PLACEHOLDER = "/*__MANIFEST_DATA__*/"

# Titles deliberately sort into a different order than dates, so a lost sort is visible.
#   date desc : Zebra, Alpha, Mid, Beta
#   title asc : Alpha, Beta, Mid, Zebra
#   2024 only : Zebra, Alpha (date desc)  vs  Alpha, Zebra (title asc)
FIXTURE_ARTICLES = [
    {"slug": "zebra", "title": "Zebra Markets", "date": "2024-03-01", "word_count": 100},
    {"slug": "alpha", "title": "Alpha Signals", "date": "2024-01-01", "word_count": 300},
    {"slug": "mid", "title": "Mid Cycle", "date": "2023-05-01", "word_count": 200},
    {"slug": "beta", "title": "Beta Curve", "date": "2023-02-01", "word_count": 400},
]


def _article(entry):
    return {"url": f"https://example.test/{entry['slug']}", "tags": [], **entry}


def _build_page(tmp_path, articles):
    """Render template.html with a synthetic manifest and empty stubs everywhere else."""
    html = TEMPLATE.read_text()
    payload = {"total_articles": len(articles), "articles": [_article(a) for a in articles]}
    for placeholder in build_dashboard.PLACEHOLDERS:
        value = build_dashboard._EMPTY_DEFAULTS.get(placeholder, "null")
        if placeholder == MANIFEST_PLACEHOLDER:
            value = json.dumps(payload)
        html = html.replace(placeholder, value)
    out = tmp_path / "index.html"
    out.write_text(html)
    return out


# --- live browser layer -----------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    manager = api.sync_playwright().start()
    try:
        launched = manager.chromium.launch()
    except Exception as exc:  # chromium not installed / can't launch
        manager.stop()
        pytest.skip(f"headless Chromium unavailable: {str(exc).splitlines()[0]}")
    yield launched
    launched.close()
    manager.stop()


@pytest.fixture
def corpus_page(browser, tmp_path):
    """Open the built page on the Raw Corpus tab, with page errors captured."""
    index = _build_page(tmp_path, FIXTURE_ARTICLES)
    page = browser.new_context().new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    page.goto(index.as_uri(), wait_until="load")
    page.click('nav button[data-tab="corpus"]')
    page.wait_for_selector(".corpus-table td")
    return page


def _titles(page):
    return page.eval_on_selector_all(
        "#corpus-tbody tr .title-cell a", "els => els.map(e => e.textContent.trim())"
    )


def test_default_order_is_newest_first(corpus_page):
    assert _titles(corpus_page) == ["Zebra Markets", "Alpha Signals", "Mid Cycle", "Beta Curve"]


def test_clicking_title_sorts_alphabetically(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    assert _titles(corpus_page) == ["Alpha Signals", "Beta Curve", "Mid Cycle", "Zebra Markets"]


def test_sort_survives_a_year_filter(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    corpus_page.select_option("#corpus-year-filter", "2024")
    # Filtering narrows the rows; it must not silently reorder them back to date-desc.
    assert _titles(corpus_page) == ["Alpha Signals", "Zebra Markets"]


def test_sort_survives_a_search(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    corpus_page.fill("#corpus-search", "e")  # drops "Alpha Signals" only
    # Title-ascending, not the date-descending order (Zebra, Mid, Beta) the bug produced.
    assert _titles(corpus_page) == ["Beta Curve", "Mid Cycle", "Zebra Markets"]


def test_sort_survives_a_theme_filter_clearing(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    corpus_page.select_option("#corpus-year-filter", "2024")
    corpus_page.select_option("#corpus-year-filter", "")  # back to All Years
    assert _titles(corpus_page) == ["Alpha Signals", "Beta Curve", "Mid Cycle", "Zebra Markets"]


def test_header_marks_the_active_sort_column(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    sorted_state = corpus_page.eval_on_selector_all(
        ".corpus-table th",
        "els => els.map(e => [e.dataset.sort || '', e.getAttribute('aria-sort')])",
    )
    assert ["title", "ascending"] in [list(pair) for pair in sorted_state]
    # Exactly one column may claim the sort.
    claimed = [p for p in sorted_state if p[1] and p[1] != "none"]
    assert len(claimed) == 1


def test_descending_sort_marks_the_header_descending(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    corpus_page.click('.corpus-table th[data-sort="title"]')
    assert _titles(corpus_page) == ["Zebra Markets", "Mid Cycle", "Beta Curve", "Alpha Signals"]
    state = corpus_page.get_attribute('.corpus-table th[data-sort="title"]', "aria-sort")
    assert state == "descending"


def test_words_sort_tolerates_a_missing_word_count(browser, tmp_path):
    """A manifest entry without `word_count` must not break the Words sort.

    `word_count` is optional in practice (Corpus II ingest writes entries that may not
    carry one). The comparator coerced a missing value to `''`, which made the
    descending branch call `.localeCompare` on a *number* — a TypeError that killed the
    whole table.
    """
    articles = [*FIXTURE_ARTICLES[:2], {"slug": "nowc", "title": "No Words", "date": "2022-01-01"}]
    index = _build_page(tmp_path, articles)
    page = browser.new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri(), wait_until="load")
    page.click('nav button[data-tab="corpus"]')
    page.wait_for_selector(".corpus-table td")

    page.click('.corpus-table th[data-sort="word_count"]')  # ascending
    page.click('.corpus-table th[data-sort="word_count"]')  # descending — used to throw

    assert errors == []
    assert _titles(page) == ["Alpha Signals", "Zebra Markets", "No Words"]


def test_no_page_errors_rendering_the_corpus_tab(corpus_page):
    corpus_page.click('.corpus-table th[data-sort="title"]')
    corpus_page.select_option("#corpus-year-filter", "2024")
    corpus_page.fill("#corpus-search", "alpha")
    assert corpus_page.errors == []


# --- structural layer (CI-safe) ---------------------------------------------------


def test_every_corpus_control_shares_one_render_path():
    """Search / year / theme / sort must all re-render through the same function.

    The defect was four call sites: the sort handler applied `currentSort`, the other
    three called `render(getFiltered())` and dropped it.
    """
    html = TEMPLATE.read_text()
    assert "function renderCorpusView()" in html
    # No control may bypass the shared path by rendering the filtered list directly.
    assert "render(getFiltered())" not in html


def test_corpus_headers_are_marked_up_as_sortable():
    html = TEMPLATE.read_text()
    for key in ("date", "title", "word_count"):
        assert f'data-sort="{key}"' in html
    assert "aria-sort" in html
