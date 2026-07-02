"""Guards the Geo-LLM verdict banner (plan 0008 step 26f) stays wired in the template.

Structural assertions on `dashboard/template.html`. The banner answers the tab's own
question ("Can the fine-tune beat retrieval?") by surfacing the 26f conclusion derived in
`analysis.geo_llm_status.voice_verdict`. It must (a) be hidden until a verdict exists and
(b) build its prose from the data fields, not hardcode a result, so a re-run that flips the
outcome flips the banner.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"


@pytest.fixture(scope="module")
def template_html() -> str:
    return TEMPLATE.read_text()


def test_verdict_container_present(template_html: str):
    assert 'id="geo-verdict"' in template_html


def test_verdict_renders_from_data(template_html: str):
    # The banner must be gated on GEO_LLM_DATA.verdict, so it stays hidden mid-experiment.
    assert "d.verdict" in template_html


def test_verdict_prose_is_data_driven(template_html: str):
    # Prose must be assembled from the structured fields, not a hardcoded outcome, so it
    # can't go stale when the eval is re-run.
    assert "finetuned_beats_rag" in template_html
    assert "finetuned_win_rate" in template_html
    assert "rag_win_rate" in template_html
