"""Structural tests for the entity co-occurrence Network dashboard tab (roadmap #14).

Two offline layers, mirroring ``test_dashboard_reading_room.py``:
  * ``build_dashboard`` wiring — the `/*__ENTITY_GRAPH_DATA__*/` placeholder is registered to
    ``entity_graph.json`` with a valid **empty-graph** default so the dashboard builds even
    before the first ``make entity-graph`` (CI / fresh clones inline the stub).
  * ``dashboard/template.html`` — the Network nav tab, the force-graph scaffold, and the JS
    hooks that render nodes (sized by article count, colored by person/org) + weighted links.

This is #14's explicitly-deferred dashboard slice; the offline builder (``entity_graph.py``)
and its committed, text-free ``entity_graph.json`` already shipped in PR #43.
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"

GRAPH_PLACEHOLDER = "/*__ENTITY_GRAPH_DATA__*/"


# --- build_dashboard wiring ------------------------------------------------------


def test_placeholder_registered_to_entity_graph_json():
    path = build_dashboard.PLACEHOLDERS[GRAPH_PLACEHOLDER]
    assert path.name == "entity_graph.json"


def test_empty_default_is_valid_empty_graph():
    stub = build_dashboard._EMPTY_DEFAULTS[GRAPH_PLACEHOLDER]
    data = json.loads(stub)
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["top_pairs"] == []


# --- template.html ---------------------------------------------------------------


def test_template_has_network_placeholder():
    assert GRAPH_PLACEHOLDER in TEMPLATE.read_text()


def test_template_has_network_nav_tab_and_container():
    html = TEMPLATE.read_text()
    assert 'data-tab="network"' in html
    assert 'id="tab-network"' in html


def test_network_wired_into_render_dispatch():
    html = TEMPLATE.read_text()
    assert "case 'network': renderNetwork(); break;" in html


def test_template_binds_entity_graph_data_and_render_fn():
    html = TEMPLATE.read_text()
    assert "ENTITY_GRAPH_DATA = /*__ENTITY_GRAPH_DATA__*/" in html
    assert "function renderNetwork" in html


def test_network_uses_force_layout_over_nodes_and_edges():
    html = TEMPLATE.read_text()
    # A force-directed graph over the builder's nodes/edges with a link force.
    assert "forceLink" in html
    assert "data.nodes" in html
    assert "data.edges" in html


def test_network_has_empty_stub_prompt():
    html = TEMPLATE.read_text()
    # When the graph is empty (CI stub), the tab prompts to build it rather than drawing nothing.
    assert "make entity-graph" in html


def test_network_redraws_on_resize():
    html = TEMPLATE.read_text()
    # The force graph measures its container at render time, so — like themes/timeline — it must
    # re-fit on viewport change. It's stateless (no in-flight user input) so a redraw is safe.
    # Assert *membership*, not the exact set literal: other stateless chart tabs join this set
    # over time, and pinning the literal made this test and the Stance one mutually exclusive —
    # a merge dropped the 'network' entry to satisfy 'stance', silently losing this redraw.
    set_line = next(
        line for line in html.splitlines() if "RESIZE_REDRAW_TABS" in line and "=" in line
    )
    assert "'network'" in set_line
