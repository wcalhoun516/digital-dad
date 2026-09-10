"""The console refuses to start on a port the public internet can reach (plan 0011 step 1).

`bin/serve_dashboard.py` is published to the internet by Tailscale Funnel and protected by
one shared password. Everything it serves today is read-only. Plan 0011 steps 2-4 add file
upload and job execution, so a guessed password would go from "reads the archive" to
"writes files and starts processes on the Mac mini". The plan makes tailnet-only listening a
hard gate, and this is that gate.

The JSON below is the real output of `tailscale serve status --json` on the machine this
project runs on, not an invented shape. It matters that it has **three** Funnels: the
dashboard's own :8443 -> 127.0.0.1:8000, plus two unrelated apps. A check that only knew
about the dashboard's port would wave the console straight onto 8501.

The probe tests drive a real subprocess against a fake `tailscale` script rather than
mocking `subprocess.run`, so the argv, exit status and stdout parsing are all exercised.
"""

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "bin" / "serve_dashboard.py"

# Verbatim from `tailscale serve status --json`, 2026-09-10.
REAL_STATUS = {
    "TCP": {"10000": {"HTTPS": True}, "443": {"HTTPS": True}, "8443": {"HTTPS": True}},
    "Web": {
        "familys-mac-mini.tailc6ef6d.ts.net:10000": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8502"}}
        },
        "familys-mac-mini.tailc6ef6d.ts.net:443": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8501"}}
        },
        "familys-mac-mini.tailc6ef6d.ts.net:8443": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}
        },
    },
    "AllowFunnel": {
        "familys-mac-mini.tailc6ef6d.ts.net:10000": True,
        "familys-mac-mini.tailc6ef6d.ts.net:443": True,
        "familys-mac-mini.tailc6ef6d.ts.net:8443": True,
    },
}


@pytest.fixture
def srv():
    spec = importlib.util.spec_from_file_location("_serve_dashboard_funnel_test", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_tailscale(tmp_path, *, stdout="", exit_code=0):
    script = tmp_path / "tailscale"
    script.write_text(f'#!/bin/sh\ncat <<\'JSON\'\n{stdout}\nJSON\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


# --- parsing the Funnel map ------------------------------------------------------------


def test_finds_every_publicly_funnelled_local_port(srv):
    assert srv.funnel_exposed_local_ports(REAL_STATUS) == {8000, 8501, 8502}


def test_the_dashboards_own_port_is_recognised_as_public(srv):
    """:8443 -> 127.0.0.1:8000 is the shipped share setup; the console must not join it."""
    assert 8000 in srv.funnel_exposed_local_ports(REAL_STATUS)


def test_tailnet_only_serve_is_not_treated_as_public(srv):
    """`tailscale serve` without Funnel is exactly what the console is supposed to use."""
    status = {
        "Web": {"host:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9000"}}}},
        "AllowFunnel": {},
    }
    assert srv.funnel_exposed_local_ports(status) == set()


def test_allow_funnel_set_to_false_is_not_public(srv):
    status = {
        "Web": {"host:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9000"}}}},
        "AllowFunnel": {"host:8443": False},
    }
    assert srv.funnel_exposed_local_ports(status) == set()


def test_raw_tcp_forwards_count_as_public(srv):
    status = {
        "TCP": {"8443": {"TCPForward": "127.0.0.1:9000"}},
        "AllowFunnel": {"host:8443": True},
    }
    assert srv.funnel_exposed_local_ports(status) == {9000}


def test_an_empty_or_unknown_status_shape_yields_no_ports(srv):
    for status in ({}, {"AllowFunnel": {"host:8443": True}}, {"Web": None}, {"TCP": "junk"}):
        assert srv.funnel_exposed_local_ports(status) == set()


# --- the refusal decision --------------------------------------------------------------


def test_refuses_when_the_listen_port_is_funnelled(srv):
    reason = srv.console_refusal_reason(8000, "ok", REAL_STATUS)
    assert reason and "8000" in reason


def test_allows_a_port_that_is_not_funnelled(srv):
    assert srv.console_refusal_reason(8999, "ok", REAL_STATUS) is None


def test_allows_when_tailscale_is_not_installed(srv):
    """No Tailscale means no Funnel, so there is nothing to refuse."""
    assert srv.console_refusal_reason(8000, "absent", None) is None


def test_refuses_when_the_funnel_state_cannot_be_determined(srv):
    """Fail closed: an unanswerable question about public exposure is not a yes."""
    reason = srv.console_refusal_reason(8000, "error", None)
    assert reason and "could not" in reason.lower()


# --- probing the real CLI --------------------------------------------------------------


def test_probe_reads_the_funnel_map_from_the_binary(srv, tmp_path):
    binary = _fake_tailscale(tmp_path, stdout=json.dumps(REAL_STATUS))
    state, status = srv.probe_funnel(binary)
    assert state == "ok"
    assert srv.funnel_exposed_local_ports(status) == {8000, 8501, 8502}


def test_probe_reports_error_when_the_cli_fails(srv, tmp_path):
    binary = _fake_tailscale(tmp_path, stdout="", exit_code=1)
    assert srv.probe_funnel(binary)[0] == "error"


def test_probe_reports_error_on_unparseable_output(srv, tmp_path):
    binary = _fake_tailscale(tmp_path, stdout="not json at all")
    assert srv.probe_funnel(binary)[0] == "error"


def test_probe_reports_absent_when_tailscale_is_not_installed(srv, monkeypatch):
    monkeypatch.setattr(srv, "find_tailscale", lambda: None)
    assert srv.probe_funnel() == ("absent", None)


# --- startup wiring --------------------------------------------------------------------


def test_main_refuses_to_start_a_funnelled_console(srv, tmp_path, capsys, monkeypatch):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(srv, "PASSWORD", "pw")
    monkeypatch.setattr(srv, "DASHBOARD_DIR", str(dashboard))
    monkeypatch.setattr(srv, "CONSOLE_ENABLED", True)
    monkeypatch.setattr(srv, "PORT", 8000)
    monkeypatch.setattr(srv, "probe_funnel", lambda binary=None: ("ok", REAL_STATUS))

    assert srv.main() == 1
    assert "REFUSING TO START" in capsys.readouterr().err


def test_main_does_not_consult_the_funnel_when_the_console_is_off(srv, tmp_path, monkeypatch):
    """The read-only family dashboard is unaffected by this gate and must still start."""
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<html></html>", encoding="utf-8")

    def _explode(binary=None):
        raise AssertionError("the Funnel must not be probed when the console is disabled")

    monkeypatch.setattr(srv, "PASSWORD", "pw")
    monkeypatch.setattr(srv, "DASHBOARD_DIR", str(dashboard))
    monkeypatch.setattr(srv, "CONSOLE_ENABLED", False)
    monkeypatch.setattr(srv, "PORT", 0)  # ephemeral: 8000 is the live dashboard's port
    monkeypatch.setattr(srv, "probe_funnel", _explode)
    monkeypatch.setattr(srv, "_serve_forever", lambda server: None)

    assert srv.main() == 0


def test_the_shipped_share_port_is_the_one_that_would_be_refused(srv):
    """Pins the real-world consequence: `make share` publishes 8000, so 8000 is off-limits."""
    default_share_port = int(os.environ.get("DIGITAL_DAD_SHARE_PORT", "8000"))
    assert default_share_port in srv.funnel_exposed_local_ports(REAL_STATUS)
