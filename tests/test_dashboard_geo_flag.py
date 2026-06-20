"""Guards the Ask Dad fine-tune flag (plan 0008 step 26e) stays wired in the template.

Structural assertions on `dashboard/template.html`. The flag is the in-repo half of 26e:
a self-revealing, default-off toggle that lets Ask Dad answer via the registered Geo-LLM
fine-tune instead of the RAG path. It must stay (a) hidden until a model is registered and
(b) off by default, so the family's experience never changes until the owner opts in.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"


@pytest.fixture(scope="module")
def template_html() -> str:
    return TEMPLATE.read_text()


def test_geo_toggle_button_present(template_html: str):
    assert 'id="chat-geo-toggle"' in template_html


def test_geo_toggle_hidden_by_default(template_html: str):
    # The button markup must start hidden so it never shows before registration.
    btn = template_html.split('id="chat-geo-toggle"', 1)[1].split(">", 1)[0]
    assert "display:none" in btn.replace(" ", "")


def test_geo_flag_defaults_off(template_html: str):
    # The JS state variable controlling the route must default to false.
    assert "useGeoFinetune = false" in template_html


def test_toggle_revealed_only_when_registered(template_html: str):
    # Visibility is gated on the registration marker surfaced as GEO_LLM_DATA.finetune.
    assert "GEO_LLM_DATA" in template_html
    assert "finetune" in template_html
    assert "model_id" in template_html


def test_request_routes_to_finetune_model_when_on(template_html: str):
    # When the flag is on, the chat request model must become the registered model_id;
    # otherwise it stays 'auto' (the existing RAG conductor route).
    assert "useGeoFinetune" in template_html
    # the model field must reference the finetune model id, not only the literal 'auto'
    assert "finetune.model_id" in template_html or "finetune?.model_id" in template_html


def test_toggle_is_wired(template_html: str):
    # The button must have a click handler that flips the flag.
    block = template_html.split('id="chat-geo-toggle"', 1)[1]
    assert "addEventListener" in template_html
    assert "geoToggle" in template_html or "chat-geo-toggle" in block or "chatGeo" in template_html
