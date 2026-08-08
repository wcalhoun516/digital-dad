"""Structural tests for the Contradictions ("Second Thoughts") dashboard tab (roadmap #15).

Two offline layers, mirroring ``test_dashboard_calhoun_isms.py`` /
``test_dashboard_intellectual_arc.py``:
  * ``build_dashboard`` wiring — the ``/*__CONTRADICTIONS_DATA__*/`` placeholder is registered
    to ``contradictions.json`` with a valid **empty** default so the dashboard builds even
    before the first ``make contradictions`` (CI / fresh clones inline the stub).
  * ``dashboard/template.html`` — the nav tab, container, data binding, render dispatch, and the
    warmed/cooled cards with an early-vs-late quote that deep-links into the Raw Corpus.

This is #15's explicitly-deferred dashboard slice; the offline builder
(``analysis/contradictions.py``) already shipped (PR #52). Its ``contradictions.json`` embeds
body excerpts, so it is git-ignored — the tab renders from the empty stub on a fresh clone and
shows a ``make contradictions`` build prompt, exactly like the Calhoun-isms / Reading Room tabs.

The const + placeholder assertions here are the guard that would have caught the calhoun-isms
regression (a merge dropped its const + placeholder, silently breaking that tab on ``main``).
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

CONTRADICTIONS_PLACEHOLDER = "/*__CONTRADICTIONS_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_contradictions_json():
    path = build_dashboard.PLACEHOLDERS[CONTRADICTIONS_PLACEHOLDER]
    assert path.name == "contradictions.json"


def test_empty_default_is_valid_empty_board():
    stub = build_dashboard._EMPTY_DEFAULTS[CONTRADICTIONS_PLACEHOLDER]
    data = json.loads(stub)
    assert data == {"meta": {}, "contradictions": []}


# --- template.html ---------------------------------------------------------------


def test_template_has_contradictions_placeholder():
    assert CONTRADICTIONS_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_contradictions_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="contradictions"' in html
    assert 'id="tab-contradictions"' in html


def test_contradictions_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'contradictions': renderContradictions(); break;" in html


def test_template_declares_contradictions_const_and_render_fn():
    html = TEMPLATE.read_text()
    assert "CONTRADICTIONS_DATA = /*__CONTRADICTIONS_DATA__*/" in html
    assert "function renderContradictions" in html


def test_render_surfaces_early_late_quotes_with_corpus_link():
    html = TEMPLATE.read_text()
    render = html.split("function renderContradictions", 1)[1].split(
        "function ", 1
    )[0]
    # Both endpoints of the reversal are drawn, and each links back to its column.
    assert "early_quote" in render
    assert "late_quote" in render
    assert "deepLinkToCorpus" in render
    # The warmed/cooled direction distinguishes the two kinds of mind-change.
    assert "warmed" in render or "cooled" in render or "direction" in render


def test_render_shows_build_prompt_when_empty():
    html = TEMPLATE.read_text()
    render = html.split("function renderContradictions", 1)[1].split(
        "function ", 1
    )[0]
    assert "make contradictions" in render
