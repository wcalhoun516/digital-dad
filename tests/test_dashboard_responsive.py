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
