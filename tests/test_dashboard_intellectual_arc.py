"""Structural tests for the Intellectual Arc dashboard tab (roadmap #13).

Two offline layers, mirroring ``test_dashboard_network.py``:
  * ``build_dashboard`` wiring — the `/*__INTELLECTUAL_ARC_DATA__*/` placeholder is registered
    to ``intellectual_arc.json`` with a valid **empty** default so the dashboard builds even
    before the first ``make intellectual-arc`` (CI / fresh clones inline the stub).
  * ``dashboard/template.html`` — the Intellectual Arc nav tab, the narrative panel, the
    per-year theme-composition viz, and the year-over-year shift cards.

This is #13's explicitly-deferred dashboard slice; the offline builder
(``intellectual_arc.py``) and its committed, text-free ``intellectual_arc.json`` already
shipped (2026-06-27).
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

ARC_PLACEHOLDER = "/*__INTELLECTUAL_ARC_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_intellectual_arc_json():
    path = build_dashboard.PLACEHOLDERS[ARC_PLACEHOLDER]
    assert path.name == "intellectual_arc.json"


def test_empty_default_is_valid_empty_arc():
    stub = build_dashboard._EMPTY_DEFAULTS[ARC_PLACEHOLDER]
    data = json.loads(stub)
    assert data["overall"] is None
    assert data["by_year"] == []
    assert data["shifts"] == []


# --- template.html ---------------------------------------------------------------


def test_template_has_arc_placeholder():
    assert ARC_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_arc_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="intellectual-arc"' in html
    assert 'id="tab-intellectual-arc"' in html


def test_arc_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'intellectual-arc': renderIntellectualArc(); break;" in html


def test_template_binds_arc_data_and_render_fn():
    html = TEMPLATE.read_text()
    assert "INTELLECTUAL_ARC_DATA = /*__INTELLECTUAL_ARC_DATA__*/" in html
    assert "function renderIntellectualArc" in html


def test_arc_renders_narrative_and_by_year_and_shifts():
    html = TEMPLATE.read_text()
    # The tab surfaces the builder's three payloads: the prose narrative, the per-year
    # theme composition, and the year-over-year shifts.
    assert ".narrative" in html
    assert ".by_year" in html
    assert ".shifts" in html


def test_arc_has_empty_stub_prompt():
    html = TEMPLATE.read_text()
    # When the arc is empty (CI stub / pre-build), the tab prompts to build it.
    assert "make intellectual-arc" in html


def test_arc_reuses_cluster_color_for_theme_consistency():
    html = TEMPLATE.read_text()
    # Bars must reuse the shared clusterColor() palette so a theme reads the same color here
    # as on the Theme Map / Timeline.
    assert "clusterColor(t.cluster_id)" in html


def test_arc_legend_click_highlights_theme_band():
    html = TEMPLATE.read_text()
    # §8.5 deepen: clicking a legend theme highlights that theme's segments across every year
    # bar (dims the rest), mirroring the Reading Room theme filter. Segments are tagged with the
    # cluster id and the legend wires a click handler that toggles the highlight.
    assert "data-arc-cluster" in html
    assert "arc-highlight" in html


def test_desktop_nav_wraps_for_thirteenth_tab():
    html = TEMPLATE.read_text()
    # The 13th tab overflows the centered desktop flex row; the base `nav` rule must wrap.
    nav_rule = html.split("nav {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in nav_rule
