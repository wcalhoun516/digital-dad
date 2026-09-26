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
