"""Structural tests for the corpus-composition panel (roadmap #38's dashboard remainder).

Mirrors ``test_dashboard_intellectual_arc.py``: `build_dashboard` wiring plus the template.

The one test here that is a *gate* rather than a transcription is
``test_empty_stub_has_exactly_the_shape_compose_returns`` — it derives the expected shape from
``compose`` itself, so adding a field to the module without adding it to the stub goes red.
Without that, a fresh clone's renderer would read ``undefined`` for the new field while every
string assertion below stayed green.
"""

import json
from pathlib import Path

import pytest

from analysis.corpus_composition import compose
from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

PLACEHOLDER = "/*__CORPUS_COMPOSITION_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_corpus_composition_json():
    assert build_dashboard.PLACEHOLDERS[PLACEHOLDER].name == "corpus_composition.json"


def test_empty_stub_is_valid_json_describing_an_empty_corpus():
    data = json.loads(build_dashboard._EMPTY_DEFAULTS[PLACEHOLDER])
    assert data["total"] == {"items": 0, "words": 0}
    assert data["by_modality"] == []
    assert data["by_authorship"] == []


def test_empty_stub_has_exactly_the_shape_compose_returns():
    """The stub is what a fresh clone renders before `make analyze` has ever run. If it drifts
    from the module's real output, the panel reads undefined fields only on fresh clones —
    which is exactly where nobody looks."""
    stub = json.loads(build_dashboard._EMPTY_DEFAULTS[PLACEHOLDER])
    real = compose({"articles": []}, readable_slugs=set())
    assert set(stub) == set(real)
    assert stub == real


# --- template.html ---------------------------------------------------------------


def test_template_binds_the_data_and_the_render_function():
    html = TEMPLATE.read_text()
    assert f"CORPUS_COMPOSITION_DATA = {PLACEHOLDER}" in html
    assert "function renderComposition" in html


def test_composition_renders_inside_the_raw_corpus_tab():
    """It belongs beside the corpus it describes rather than as an 18th nav tab."""
    html = TEMPLATE.read_text()
    assert "renderComposition();" in html
    assert 'id="composition-tbody"' in html


def test_the_panel_says_it_measures_words_rather_than_documents():
    """The headline judgement of #38's remainder. One book is worth ~50 columns, so a reader
    who assumes these are document counts misreads the archive."""
    html = TEMPLATE.read_text()
    panel = html.split('id="tab-corpus"', 1)[1].split('id="tab-search"', 1)[0]
    assert "words" in panel.lower()


def test_the_panel_reports_material_the_pipeline_cannot_read():
    html = TEMPLATE.read_text()
    assert 'id="composition-unreadable"' in html
    assert ".unreadable" in html


def test_the_panel_builds_rows_without_innerhtml():
    """Rows are named from ingested documents' provenance. Treating any of it as markup would
    let a dropped file run script in the family's browser."""
    render = TEMPLATE.read_text().split("function renderComposition", 1)[1]
    render = render.split("function renderCorpus", 1)[0]
    assert ".innerHTML" not in render
    assert "createElement" in render
    assert "textContent" in render


def test_the_panel_prompts_a_build_when_the_composition_is_empty():
    render = TEMPLATE.read_text().split("function renderComposition", 1)[1]
    render = render.split("function renderCorpus", 1)[0]
    assert "make analyze" in render


# --- live ------------------------------------------------------------------------------
#
# Everything above reads the template as a string, which cannot tell whether the panel
# actually renders. These load the real template in a real browser, click the real nav
# button, and read the resulting DOM. Precedent: tests/test_console_page.py::TestLiveJobPanel.


HOSTILE_MODALITY = "<img src=x onerror=window.__pwned=1>"

LIVE_COMPOSITION = {
    "total": {"items": 4, "words": 83904},
    "readable": {"items": 2, "words": 3004},
    "unreadable": {"items": 2, "words": 80900},
    "by_modality": [
        {"name": "book", "items": 1, "words": 80000, "share": 80000 / 83904},
        {"name": "article", "items": 2, "words": 3004, "share": 3004 / 83904},
        {"name": HOSTILE_MODALITY, "items": 1, "words": 900, "share": 900 / 83904},
    ],
    "by_authorship": [
        {"name": "george", "items": 3, "words": 83004, "share": 83004 / 83904},
        {"name": "mixed", "items": 1, "words": 900, "share": 900 / 83904},
    ],
}


def _render_page(tmp_path, composition: dict) -> Path:
    """Inject *composition* into the real template the way `make dashboard` does."""
    html = TEMPLATE.read_text()
    for placeholder in build_dashboard.PLACEHOLDERS:
        if placeholder == PLACEHOLDER:
            data = json.dumps(composition)
        elif placeholder == build_dashboard.MANIFEST_PLACEHOLDER:
            data = '{"last_updated":"","total_articles":0,"articles":[]}'
        else:
            data = build_dashboard._EMPTY_DEFAULTS.get(placeholder, "null")
        html = html.replace(placeholder, data)
    page = tmp_path / "index.html"
    page.write_text(html)
    return page


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
def panel(browser, tmp_path):
    """The composition panel as a reader reaches it: open the page, click Raw Corpus."""
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(_render_page(tmp_path, LIVE_COMPOSITION).as_uri())
    page.click('nav button[data-tab="corpus"]')
    page.wait_for_selector("#composition-tbody tr")
    yield page, errors
    page.close()


class TestLiveCompositionPanel:
    def test_clicking_raw_corpus_renders_one_row_per_modality(self, panel):
        page, errors = panel
        assert page.eval_on_selector_all("#composition-tbody tr", "rows => rows.length") == 3
        assert errors == []

    def test_the_book_outranks_the_articles_on_screen(self, panel):
        """The panel's whole reason for existing: read top-down, the biggest *word* count
        leads. An item-count panel would have put the two articles first."""
        page, _ = panel
        names = page.eval_on_selector_all(
            "#composition-tbody tr td:first-child", "cells => cells.map(c => c.textContent)"
        )
        assert names[0] == "book"
        assert names[1] == "article"

    def test_a_modality_name_carrying_markup_renders_as_text(self, panel):
        """Modality names come from ingested documents' provenance, which the operator can
        set. If the panel treated one as markup, a crafted document would run script in the
        family's browser — so assert on the DOM, not on the absence of `.innerHTML` in
        source."""
        page, _ = panel
        names = page.eval_on_selector_all(
            "#composition-tbody tr td:first-child", "cells => cells.map(c => c.textContent)"
        )
        assert HOSTILE_MODALITY in names
        assert page.evaluate("window.__pwned === undefined")
        assert page.eval_on_selector_all("#composition-tbody img", "els => els.length") == 0

    def test_unreadable_material_is_visible_not_merely_present(self, panel):
        """The note is built hidden. A panel that renders it into a `hidden` element reports
        80,900 gathered words that reach no model — and says nothing."""
        page, _ = panel
        assert page.is_visible("#composition-unreadable")
        assert "80,900" in page.text_content("#composition-unreadable")

    def test_a_fresh_clone_sees_a_build_prompt_instead_of_an_empty_table(
        self, browser, tmp_path
    ):
        stub = json.loads(build_dashboard._EMPTY_DEFAULTS[PLACEHOLDER])
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(_render_page(tmp_path, stub).as_uri())
        page.click('nav button[data-tab="corpus"]')
        # Tab renders are deferred ~50ms after the click so display:block lands before D3
        # measures container widths (template.html, "Small delay to let display:block take
        # effect"). Wait for the render rather than for a duration.
        page.wait_for_function(
            "document.getElementById('composition-summary').textContent.length > 0"
        )
        assert "make analyze" in page.text_content("#composition-summary")
        assert page.is_hidden("#composition-table")
        assert errors == []
        page.close()
