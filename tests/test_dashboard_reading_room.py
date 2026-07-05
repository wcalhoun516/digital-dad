"""Structural tests for the Reading Room dashboard tab (roadmap #21).

Two layers, both offline:
  * ``build_dashboard`` wiring — the `/*__READING_ROOM_DATA__*/` placeholder is registered
    with a valid **empty-room** default so the dashboard builds body-free in CI / fresh clones.
  * ``dashboard/template.html`` — the Reading Room nav tab, reader scaffold, and the JS hooks
    that render entries with prev/next + theme + a Forbes deep link.
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

READING_ROOM_PLACEHOLDER = "/*__READING_ROOM_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_reading_room_json():
    path = build_dashboard.PLACEHOLDERS[READING_ROOM_PLACEHOLDER]
    assert path.name == "reading_room.json"


def test_empty_default_is_valid_empty_room():
    stub = build_dashboard._EMPTY_DEFAULTS[READING_ROOM_PLACEHOLDER]
    data = json.loads(stub)
    assert data == {"entries": [], "count": 0, "themes": []}


# --- template.html ---------------------------------------------------------------


def test_template_has_reading_room_placeholder():
    assert READING_ROOM_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_reading_room_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="reading-room"' in html
    assert 'id="tab-reading-room"' in html


def test_reading_room_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'reading-room': renderReadingRoom(); break;" in html


def test_template_reader_renders_prev_next_theme_and_forbes_link():
    html = TEMPLATE.read_text()
    # The reader reads the inlined reading-room data and has a render entry point.
    assert "READING_ROOM_DATA = /*__READING_ROOM_DATA__*/" in html
    assert "function renderReadingRoom" in html
    # Prev/next navigation between articles and a Forbes deep link for the open one.
    assert "rr-prev" in html and "rr-next" in html
    assert "Read on Forbes" in html


def test_template_has_theme_filter_over_emitted_themes():
    html = TEMPLATE.read_text()
    # A theme filter (populated from the builder's `themes`) narrows the index list.
    assert 'id="rr-theme-filter"' in html
    assert "data-theme=" in html
