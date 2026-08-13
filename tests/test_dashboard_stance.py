"""Structural tests for the Stance-over-time dashboard tab (roadmap #17 viz slice).

Two offline layers, mirroring ``test_dashboard_network.py`` / ``test_dashboard_reading_room.py``:
  * ``build_dashboard`` wiring — the `/*__ENTITY_STANCE_DATA__*/` placeholder is registered with
    a valid **empty-graph** default so the dashboard builds in CI / a fresh clone that has no
    ``entity_stance.json`` yet.
  * ``dashboard/template.html`` — the Stance nav tab, its container, the inlined data const, the
    ``renderStance`` render entry point wired into the dispatcher, and its resize-redraw membership.
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

STANCE_PLACEHOLDER = "/*__ENTITY_STANCE_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_entity_stance_json():
    path = build_dashboard.PLACEHOLDERS[STANCE_PLACEHOLDER]
    assert path.name == "entity_stance.json"


def test_empty_default_is_valid_empty_graph():
    stub = build_dashboard._EMPTY_DEFAULTS[STANCE_PLACEHOLDER]
    data = json.loads(stub)
    assert data == {"meta": {}, "entities": [], "warming": [], "cooling": []}


# --- template.html ---------------------------------------------------------------


def test_template_has_stance_placeholder():
    assert STANCE_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_stance_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="stance"' in html
    assert 'id="tab-stance"' in html


def test_stance_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'stance': renderStance(); break;" in html


def test_template_inlines_stance_data_and_renderer():
    html = TEMPLATE.read_text()
    assert "ENTITY_STANCE_DATA = /*__ENTITY_STANCE_DATA__*/" in html
    assert "function renderStance" in html


def test_stance_renders_trajectories_and_trend_boards():
    html = TEMPLATE.read_text()
    # Multi-line trajectory chart reads each entity's yearly trajectory + a warming/cooling board.
    assert "trajectory" in html
    assert "warming" in html and "cooling" in html


def test_stance_has_empty_stub_prompt():
    html = TEMPLATE.read_text()
    # A fresh clone with the empty stub shows a build prompt, not a blank canvas.
    assert "make entity-stance" in html


def test_stance_is_resize_redraw_tab():
    html = TEMPLATE.read_text()
    # Membership, not the exact set literal — see the matching note in
    # ``test_dashboard_network.py``: pinning the literal made the two tests mutually exclusive.
    set_line = next(
        line for line in html.splitlines() if "RESIZE_REDRAW_TABS" in line and "=" in line
    )
    assert "'stance'" in set_line


def test_desktop_nav_wraps_so_added_tab_cannot_overflow():
    # Adding a 12th tab pushes the non-wrapping desktop nav past 1280px, causing a
    # horizontal scroll. The base `nav` rule must wrap so extra tabs flow to a second row.
    html = TEMPLATE.read_text()
    nav_rule = html.split("nav {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in nav_rule
