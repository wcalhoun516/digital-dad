"""Auth gate over the operator-console routes (plan 0011 step 1).

`bin/serve_dashboard.py` had no tests at all before this file, which is a poor place to
start adding routes that will later write files and start jobs (plan 0011 steps 2-4).
Everything here drives a **real** `ThreadingHTTPServer` over a real socket — the gate is
an HTTP-level property, and a unit test that called `_authed()` directly would prove
nothing about whether the handler actually calls it.

The route table is read from the module (`CONSOLE_ROUTES`), not repeated here, so a route
added in a later step joins these tests automatically instead of quietly skipping them.
"""

import base64
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "bin" / "serve_dashboard.py"
PASSWORD = "correct-horse"


def _load_server_module():
    """Import bin/serve_dashboard.py by path — bin/ is scripts, not an importable package."""
    spec = importlib.util.spec_from_file_location("_serve_dashboard_under_test", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def serve_dashboard():
    return _load_server_module()


@pytest.fixture
def dashboard_dir(tmp_path):
    (tmp_path / "index.html").write_text("<html>family dashboard</html>", encoding="utf-8")
    (tmp_path / "console.html").write_text("<html>operator console</html>", encoding="utf-8")
    return tmp_path


@pytest.fixture
def base_url(serve_dashboard, dashboard_dir):
    """A live gated server on an ephemeral port; console enabled unless a test disables it."""
    serve_dashboard.PASSWORD = PASSWORD
    serve_dashboard.CONSOLE_ENABLED = True
    handler = partial(serve_dashboard.GatedHandler, directory=str(dashboard_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(url, *, method="GET", password=None, data=None):
    """Return (status, headers, body). A 4xx/5xx is a result here, not an exception."""
    req = urllib.request.Request(url, method=method, data=data)
    if password is not None:
        token = base64.b64encode(f"operator:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


# --- the route table itself ------------------------------------------------------------


def test_console_routes_are_declared(serve_dashboard):
    routes = serve_dashboard.CONSOLE_ROUTES
    assert routes, "CONSOLE_ROUTES must list every console route so the gate test can enumerate it"
    for route in routes:
        assert route == "/console" or route.startswith("/console/api/"), route


# --- the gate --------------------------------------------------------------------------


def test_every_console_route_401s_without_auth(serve_dashboard, base_url):
    for route in serve_dashboard.CONSOLE_ROUTES:
        status, headers, _ = _request(base_url + route)
        assert status == 401, f"{route} served without auth"
        assert "Basic" in headers.get("WWW-Authenticate", ""), route


def test_every_console_route_401s_on_post_without_auth(serve_dashboard, base_url):
    for route in serve_dashboard.CONSOLE_ROUTES:
        status, _, _ = _request(base_url + route, method="POST", data=b"{}")
        assert status == 401, f"{route} accepted an unauthenticated POST"


def test_every_console_route_401s_with_a_wrong_password(serve_dashboard, base_url):
    for route in serve_dashboard.CONSOLE_ROUTES:
        status, _, _ = _request(base_url + route, password="wrong")
        assert status == 401, f"{route} accepted the wrong password"


def test_console_routes_are_gated_even_when_the_console_is_disabled(serve_dashboard, base_url):
    """Disabled must not mean unguarded — a 404 would still confirm the route to a stranger."""
    serve_dashboard.CONSOLE_ENABLED = False
    for route in serve_dashboard.CONSOLE_ROUTES:
        status, _, _ = _request(base_url + route)
        assert status == 401, f"{route} answered an unauthenticated request while disabled"


# --- dispatch --------------------------------------------------------------------------


def test_console_page_is_served_when_enabled(base_url):
    status, headers, body = _request(base_url + "/console", password=PASSWORD)
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"operator console" in body


def test_console_api_health_reports_enabled(base_url):
    status, headers, body = _request(base_url + "/console/api/health", password=PASSWORD)
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["console"] == "enabled"


def test_console_routes_404_when_disabled(serve_dashboard, base_url):
    serve_dashboard.CONSOLE_ENABLED = False
    for route in serve_dashboard.CONSOLE_ROUTES:
        status, _, _ = _request(base_url + route, password=PASSWORD)
        assert status == 404, f"{route} responded while the console was disabled"


def test_console_is_disabled_unless_the_env_var_is_exactly_1(monkeypatch):
    """Default-off: the console is opt-in, so a stray or absent value must not enable it."""
    for value, expected in (("1", True), ("0", False), ("true", False), ("", False)):
        monkeypatch.setenv("DIGITAL_DAD_CONSOLE", value)
        assert _load_server_module().CONSOLE_ENABLED is expected, value
    monkeypatch.delenv("DIGITAL_DAD_CONSOLE")
    assert _load_server_module().CONSOLE_ENABLED is False


def test_unknown_console_api_route_is_404_not_405(base_url):
    status, _, _ = _request(base_url + "/console/api/nope", password=PASSWORD, method="POST")
    assert status == 404


# --- the console page must not leak through the static handler -------------------------
#
# `console.html` lives in the directory this server publishes, and that directory is what
# Tailscale Funnel exposes to the public internet. Routing `/console` is not enough on its
# own: `/console.html` is a plain file in the served tree and the static handler will hand
# it over. D4 keeps the family artifact self-contained; the console is the opposite kind of
# surface and must not ride along in it.


def test_console_page_is_not_served_statically_when_disabled(serve_dashboard, base_url):
    serve_dashboard.CONSOLE_ENABLED = False
    status, _, _ = _request(base_url + "/console.html", password=PASSWORD)
    assert status == 404


def test_console_page_is_not_head_addressable_when_disabled(serve_dashboard, base_url):
    serve_dashboard.CONSOLE_ENABLED = False
    status, _, _ = _request(base_url + "/console.html", method="HEAD", password=PASSWORD)
    assert status == 404


def test_console_page_static_path_still_requires_the_password(serve_dashboard, base_url):
    serve_dashboard.CONSOLE_ENABLED = False
    status, _, _ = _request(base_url + "/console.html")
    assert status == 401


# --- the family dashboard is untouched -------------------------------------------------


def test_dashboard_still_requires_the_password(base_url):
    status, _, _ = _request(base_url + "/index.html")
    assert status == 401


def test_dashboard_is_still_served_with_the_password(base_url):
    status, _, body = _request(base_url + "/index.html", password=PASSWORD)
    assert status == 200
    assert b"family dashboard" in body


def test_non_console_post_is_still_405(base_url):
    status, _, _ = _request(base_url + "/index.html", method="POST", data=b"x", password=PASSWORD)
    assert status == 405
