"""Tests for analysis/conductor.py — the shared conductor preflight helper.

Roadmap #6. One health check + one clear error message, shared by every
owner-gated CLI instead of three copy-pasted ``_conductor_up()`` functions.

The health check's only network call sits behind an injectable ``opener``, so
these tests touch no conductor and no network.
"""

import io
import urllib.error

from analysis.conductor import (
    CONDUCTOR_BASE_URL,
    conductor_up,
    require_conductor,
    unreachable_message,
)


class _FakeResp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener_returning(status, calls=None):
    def opener(url, timeout=None):
        if calls is not None:
            calls.append((url, timeout))
        return _FakeResp(status)
    return opener


def _opener_raising(exc):
    def opener(url, timeout=None):
        raise exc
    return opener


class TestConductorUp:
    def test_true_on_200(self):
        assert conductor_up(opener=_opener_returning(200)) is True

    def test_false_on_non_200(self):
        assert conductor_up(opener=_opener_returning(503)) is False

    def test_false_on_urlerror(self):
        opener = _opener_raising(urllib.error.URLError("refused"))
        assert conductor_up(opener=opener) is False

    def test_false_on_oserror(self):
        assert conductor_up(opener=_opener_raising(OSError("boom"))) is False

    def test_hits_models_endpoint(self):
        calls = []
        conductor_up(opener=_opener_returning(200, calls))
        assert calls and calls[0][0] == CONDUCTOR_BASE_URL.rstrip("/") + "/models"

    def test_respects_custom_base_url_and_trailing_slash(self):
        calls = []
        conductor_up(base_url="http://host:9000/v1/", opener=_opener_returning(200, calls))
        assert calls[0][0] == "http://host:9000/v1/models"

    def test_passes_timeout(self):
        calls = []
        conductor_up(timeout=7, opener=_opener_returning(200, calls))
        assert calls[0][1] == 7


class TestUnreachableMessage:
    def test_mentions_unreachable_and_url(self):
        msg = unreachable_message()
        assert "unreachable" in msg.lower()
        assert "127.0.0.1:8080" in msg

    def test_includes_extra(self):
        msg = unreachable_message(extra="Tip: use --style-only.")
        assert "Tip: use --style-only." in msg

    def test_no_dangling_none_without_extra(self):
        assert "None" not in unreachable_message()


class TestRequireConductor:
    def test_true_when_up(self):
        assert require_conductor(opener=_opener_returning(200)) is True

    def test_false_when_down(self):
        out = io.StringIO()
        assert require_conductor(opener=_opener_returning(503), stream=out) is False

    def test_prints_message_when_down(self):
        out = io.StringIO()
        require_conductor(opener=_opener_raising(OSError()), stream=out)
        assert "unreachable" in out.getvalue().lower()

    def test_extra_reaches_printed_message(self):
        out = io.StringIO()
        require_conductor(opener=_opener_returning(503), stream=out, extra="ZZTOP")
        assert "ZZTOP" in out.getvalue()

    def test_silent_when_up(self):
        out = io.StringIO()
        require_conductor(opener=_opener_returning(200), stream=out)
        assert out.getvalue() == ""
