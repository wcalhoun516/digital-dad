"""Guards the mobile-responsive CSS layer (plan 0006) stays in the dashboard template.

These are structural assertions on the single source file `dashboard/template.html`:
the family opens the dashboard on phones, so the responsive layer must not silently
disappear in a future refactor.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"


@pytest.fixture(scope="module")
def template_html() -> str:
    return TEMPLATE.read_text()


def test_viewport_meta_present(template_html: str):
    assert 'name="viewport"' in template_html
    assert "width=device-width" in template_html


def test_responsive_layer_present(template_html: str):
    # The labelled block must exist so the layer is discoverable.
    assert "RESPONSIVE / MOBILE" in template_html
    # Two breakpoints: tablet/handset and small-phone.
    assert "@media (max-width: 768px)" in template_html
    assert "@media (max-width: 480px)" in template_html


def test_tab_bar_scrolls_on_mobile(template_html: str):
    # The 9-tab nav must scroll horizontally instead of overflowing the viewport.
    block = template_html.split("RESPONSIVE / MOBILE", 1)[1]
    assert "nav {" in block
    assert "overflow-x: auto" in block


def test_chart_grid_collapses_on_mobile(template_html: str):
    # The desktop grid uses minmax(400px,...) which overflows a 375px screen.
    block = template_html.split("RESPONSIVE / MOBILE", 1)[1]
    assert ".chart-grid" in block
    assert "grid-template-columns: 1fr" in block


def test_wide_tables_scroll_on_mobile(template_html: str):
    block = template_html.split("RESPONSIVE / MOBILE", 1)[1]
    assert ".corpus-table" in block


def test_radar_svg_scales(template_html: str):
    # The radar is the one fixed-size (400x400) chart; a viewBox + max-width
    # rule lets it shrink to fit a phone instead of forcing horizontal scroll.
    assert 'id="radar-svg"' in template_html
    assert 'viewBox="0 0 400 400"' in template_html
    assert "#radar-svg { max-width: 100%; height: auto; }" in template_html


# ===== plan 0006, step 2: D3 charts resize to their container =====
# The pixel-sized D3 charts (theme map, timeline) measure their container only
# at first render. On a viewport change (window resize / phone orientation flip)
# they keep stale dimensions, so the family sees a chart that doesn't fit. These
# guard the resize-redraw layer.

REDRAW_MARKER = "RESPONSIVE REDRAW"


@pytest.fixture(scope="module")
def redraw_block(template_html: str) -> str:
    assert REDRAW_MARKER in template_html, "resize-redraw layer is missing"
    return template_html.split(REDRAW_MARKER, 1)[1]


def test_charts_redraw_on_window_resize(redraw_block: str):
    # A window resize must trigger a re-render of the active chart.
    assert "window.addEventListener('resize'" in redraw_block


def test_resize_redraw_is_debounced(redraw_block: str):
    # A drag-resize fires dozens of events; debounce so we redraw once.
    assert "clearTimeout" in redraw_block
    assert "setTimeout" in redraw_block


def test_resize_redraw_only_redraws_stateless_chart_tabs(redraw_block: str):
    # Re-rendering must be restricted to the stateless chart tabs. Redrawing an
    # interactive tab (Ask Dad chat, Corpus filters) would wipe in-flight state.
    set_line = next(
        line for line in redraw_block.splitlines() if "RESIZE_REDRAW_TABS" in line and "=" in line
    )
    assert "'themes'" in set_line
    assert "'timeline'" in set_line
    assert "askdad" not in set_line
    assert "corpus" not in set_line


def test_theme_map_clears_legend_before_redraw(template_html: str):
    # renderThemeMap appends legend items; without clearing first, a redraw
    # duplicates the whole legend. Must reset it to be idempotent.
    assert "legend.innerHTML = ''" in template_html


def test_chart_renders_clear_svg_before_redraw(template_html: str):
    # Both pixel-sized charts must wipe their SVG before drawing so a redraw
    # doesn't stack duplicate axes/nodes. Expect a clear in each.
    assert template_html.count("selectAll('*').remove()") >= 2


def test_timeline_toggle_does_not_stack_listeners(template_html: str):
    # The sentiment toggle must use onclick assignment, not addEventListener,
    # so repeated redraws don't pile up duplicate click handlers.
    assert "toggleBtn.onclick" in template_html
