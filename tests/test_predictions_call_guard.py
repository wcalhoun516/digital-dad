"""The T3 privacy guard, wired into the one place that actually sets ``allow_remote``.

``analysis/predictions.py::_call`` is the single Python chokepoint for remote conductor
calls — ``verdict_backfill``, ``voice_eval`` and ``rag_eval`` all import it rather than
building their own request. Guarding it guards all four. These tests use a fake client and
touch no network.
"""

import pytest

from analysis import predictions
from analysis.conductor import PrivateContentError
from ingest.provenance import default_provenance

PUBLIC = default_provenance(source_id="a-forbes-column", privacy="public", license="forbes")
PRIVATE = default_provenance(source_id="a-letter", modality="letter", privacy="private")


class _FakeClient:
    """Records every request instead of making one."""

    def __init__(self, reply="ok"):
        self.requests = []
        self.chat = self
        self.completions = self
        self._reply = reply

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = type("M", (), {"content": self._reply})
        choice = type("C", (), {"message": message})
        return type("R", (), {"choices": [choice]})


@pytest.fixture
def no_sleeping(monkeypatch):
    """A refusal must be instant — never fed into ``_call``'s 3x retry/backoff loop."""
    def explode(_seconds):
        raise AssertionError("a refused call must not sleep or retry")
    monkeypatch.setattr(predictions.time, "sleep", explode)


# --------------------------------------------------------------------------- #
# Remote tier: declaration required
# --------------------------------------------------------------------------- #

def test_remote_call_without_declared_sources_is_refused(no_sleeping):
    client = _FakeClient()
    with pytest.raises(PrivateContentError):
        predictions._call(client, "prompt", tier=3)
    assert client.requests == [], "refused before anything reached the conductor"


def test_remote_call_carrying_private_material_is_refused(no_sleeping):
    client = _FakeClient()
    with pytest.raises(PrivateContentError) as excinfo:
        predictions._call(client, "prompt", tier=3, sources=[PUBLIC, PRIVATE])
    assert "a-letter" in str(excinfo.value)
    assert client.requests == []


def test_remote_call_with_public_sources_proceeds_and_allows_remote():
    client = _FakeClient()
    assert predictions._call(client, "prompt", tier=3, sources=[PUBLIC]) == "ok"
    assert client.requests[0]["extra_body"]["allow_remote"] is True
    assert client.requests[0]["extra_body"]["tier"] == 3


def test_remote_call_declaring_no_corpus_material_proceeds():
    """A judge ranking model-generated text sends nothing from the corpus."""
    client = _FakeClient()
    assert predictions._call(client, "prompt", tier=3, sources=[]) == "ok"
    assert client.requests[0]["extra_body"]["allow_remote"] is True


# --------------------------------------------------------------------------- #
# Local tiers: nothing leaves the machine, so nothing to declare
# --------------------------------------------------------------------------- #

def test_local_call_needs_no_declaration():
    client = _FakeClient()
    assert predictions._call(client, "prompt", tier=2) == "ok"
    assert "allow_remote" not in client.requests[0]["extra_body"]


def test_private_material_is_fine_on_a_local_tier():
    """The point of a local conductor is that his letters can be analysed at all."""
    client = _FakeClient()
    assert predictions._call(client, "prompt", tier=2, sources=[PRIVATE]) == "ok"
    assert "allow_remote" not in client.requests[0]["extra_body"]
