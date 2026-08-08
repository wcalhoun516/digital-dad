"""Structural tests for the Calhoun-isms dashboard tab (roadmap #16 deferred viz).

Two layers, both offline:
  * ``build_dashboard`` wiring — the ``/*__CALHOUN_ISMS_DATA__*/`` placeholder is registered
    with a valid **empty** default so the dashboard builds text-free in CI / fresh clones
    (the artifact embeds article-body excerpts, so it is git-ignored like ``reading_room.json``).
  * ``dashboard/template.html`` — the Calhoun-isms nav tab, board scaffold, and the JS hooks
    that render the overall + per-theme aphorism boards with a click-through to the corpus.
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

CALHOUN_ISMS_PLACEHOLDER = "/*__CALHOUN_ISMS_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_calhoun_isms_json():
    path = build_dashboard.PLACEHOLDERS[CALHOUN_ISMS_PLACEHOLDER]
    assert path.name == "calhoun_isms.json"


def test_empty_default_is_valid_empty_board():
    stub = build_dashboard._EMPTY_DEFAULTS[CALHOUN_ISMS_PLACEHOLDER]
    data = json.loads(stub)
    assert data == {"meta": {}, "themes": [], "overall_top": []}


# --- template.html ---------------------------------------------------------------


def test_template_has_calhoun_isms_placeholder():
    assert CALHOUN_ISMS_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_calhoun_isms_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="calhoun-isms"' in html
    assert 'id="tab-calhoun-isms"' in html


def test_calhoun_isms_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'calhoun-isms': renderCalhounIsms(); break;" in html


def test_template_declares_calhoun_isms_const_and_render_fn():
    html = TEMPLATE.read_text()
    assert "CALHOUN_ISMS_DATA = /*__CALHOUN_ISMS_DATA__*/" in html
    assert "function renderCalhounIsms" in html


def test_render_surfaces_overall_and_theme_boards_with_corpus_link():
    html = TEMPLATE.read_text()
    # The overall "most quotable" board and the per-theme sections are both drawn.
    assert "overall_top" in html
    # Each aphorism links back to its article via the existing corpus deep-link helper.
    assert "deepLinkToCorpus" in html


def test_render_shows_build_prompt_when_empty():
    html = TEMPLATE.read_text()
    assert "make calhoun-isms" in html


def test_nav_wraps_so_thirteenth_tab_does_not_overflow():
    # The desktop nav is a centered flex row; adding a 13th tab overflows it unless it wraps.
    html = TEMPLATE.read_text()
    nav_css = html.split("nav {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in nav_css
