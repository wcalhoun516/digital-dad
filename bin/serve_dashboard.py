#!/usr/bin/env python3
"""Password-gated static server for the digital-dad dashboard, with a conductor proxy.

`make serve` runs a plain `python -m http.server`, which has NO authentication —
fine for localhost, unsafe the moment the dashboard is exposed to the internet via
Tailscale Funnel. This server is the access-control layer for remote sharing:

  • binds 127.0.0.1 only (the Funnel is the sole public ingress; see
    scripts/launchd/install_dashboard.sh and the dashboard-remote-sharing playbook),
  • gates every request behind HTTP Basic Auth (any username; the password is the
    real check), so the non-indexed .ts.net link can't be opened without the password,
  • reverse-proxies /v1/* to the local-llm-conductor (127.0.0.1:8080) so the
    browser-side "Ask Dad" chat and semantic search work for a REMOTE visitor —
    their browser hits the Funnel (same origin), not their own localhost.

Basic Auth credentials travel encrypted because Funnel terminates TLS (HTTPS).

Env:
  DIGITAL_DAD_DASHBOARD_PASSWORD   required to enable the gate (unset → OPEN, refuses
                                   to run unless DIGITAL_DAD_ALLOW_OPEN=1)
  DIGITAL_DAD_SHARE_PORT           listen port (default 8000)
  DIGITAL_DAD_SHARE_ADDRESS        bind address (default 127.0.0.1)
  DIGITAL_DAD_DASHBOARD_DIR        dir to serve (default <repo>/dashboard)
  DIGITAL_DAD_CONDUCTOR_URL        conductor base (default http://127.0.0.1:8080)

Manual run:  DIGITAL_DAD_DASHBOARD_PASSWORD=GeoLLM .venv/bin/python bin/serve_dashboard.py
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

PASSWORD = os.environ.get("DIGITAL_DAD_DASHBOARD_PASSWORD", "")
PORT = int(os.environ.get("DIGITAL_DAD_SHARE_PORT", "8000"))
ADDRESS = os.environ.get("DIGITAL_DAD_SHARE_ADDRESS", "127.0.0.1")
CONDUCTOR_URL = os.environ.get("DIGITAL_DAD_CONDUCTOR_URL", "http://127.0.0.1:8080").rstrip("/")
REALM = "digital-dad dashboard"

# The operator console (plan 0011) is opt-in: it is a WRITE surface, and this server is the
# same one published to the public internet by Tailscale Funnel. Anything other than exactly
# "1" leaves it off.
CONSOLE_ENABLED = os.environ.get("DIGITAL_DAD_CONSOLE") == "1"

# Every console route, in one place. tests/test_console_gate.py enumerates this tuple to
# assert each route 401s unauthenticated, so a route added here cannot skip the gate test.
CONSOLE_ROUTES = (
    "/console",
    "/console/api/health",
    "/console/api/upload",
    "/console/api/queue",
    "/console/api/review",
)

# Where the console reads and writes. None means "whatever the ingest modules default to",
# so the on-disk layout stays defined in ingest/queue.py rather than restated here; tests
# point these at a tmp dir.
CONSOLE_INBOX_DIR = None
CONSOLE_QUEUE_DIR = None
CONSOLE_MANIFEST_PATH = None

# A review decision is a handful of short strings. Anything larger is not one, and reading it
# into memory before finding that out is the mistake.
MAX_JSON_BYTES = 64 * 1024

# The console's page is a plain file inside the directory this server publishes, so routing
# /console is not by itself enough to keep it out of the family artifact — the static handler
# will hand over /console.html to anyone holding the dashboard password. With the console off,
# these paths do not exist.
CONSOLE_STATIC_PATHS = ("/console.html",)

# The Tailscale CLI is not on PATH for a launchd job on macOS.
_MACOS_TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_DIR = os.environ.get("DIGITAL_DAD_DASHBOARD_DIR", os.path.join(_REPO_ROOT, "dashboard"))

# Hop-by-hop headers must not be forwarded through a proxy (RFC 7230 §6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def _proxy_target_port(target: str) -> int | None:
    """Local port out of a serve target: 'http://127.0.0.1:8000' or '127.0.0.1:8000'."""
    if not isinstance(target, str):
        return None
    _, _, hostport = target.rpartition("/")
    _, _, port = hostport.rpartition(":")
    return int(port) if port.isdigit() else None


def funnel_exposed_local_ports(status: dict) -> set[int]:
    """Local ports the PUBLIC internet can reach, per `tailscale serve status --json`.

    Only entries whose host:port is flagged in AllowFunnel count — a plain `tailscale serve`
    is tailnet-only, and that is the mode the console is meant to run behind.
    """
    if not isinstance(status, dict):
        return set()
    allow = status.get("AllowFunnel")
    if not isinstance(allow, dict):
        return set()
    public = {hostport for hostport, on in allow.items() if on}
    web = status.get("Web") if isinstance(status.get("Web"), dict) else {}
    tcp = status.get("TCP") if isinstance(status.get("TCP"), dict) else {}

    ports: set[int] = set()
    for hostport in public:
        entry = web.get(hostport)
        if isinstance(entry, dict) and isinstance(entry.get("Handlers"), dict):
            for handler in entry["Handlers"].values():
                if isinstance(handler, dict):
                    port = _proxy_target_port(handler.get("Proxy"))
                    if port is not None:
                        ports.add(port)
        _, _, public_port = hostport.rpartition(":")
        forward = tcp.get(public_port)
        if isinstance(forward, dict):
            port = _proxy_target_port(forward.get("TCPForward"))
            if port is not None:
                ports.add(port)
    return ports


def find_tailscale() -> str | None:
    return shutil.which("tailscale") or (
        _MACOS_TAILSCALE if os.path.isfile(_MACOS_TAILSCALE) else None
    )


def probe_funnel(binary: str | None = None) -> tuple[str, dict | None]:
    """('absent'|'ok'|'error', status). 'absent' means no Tailscale, so no Funnel exists."""
    binary = binary or find_tailscale()
    if not binary:
        return "absent", None
    try:
        done = subprocess.run(
            [binary, "serve", "status", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if done.returncode != 0:
            return "error", None
        return "ok", json.loads(done.stdout)
    except Exception:
        return "error", None


def console_refusal_reason(listen_port: int, state: str, status: dict | None) -> str | None:
    """Why the console must not start on this port, or None if it may.

    Fails closed: if Tailscale is installed but its Funnel map cannot be read, the question
    "is this port public?" is unanswered, and an unanswered question is not a yes.
    """
    if state == "absent":
        return None
    if state != "ok" or not isinstance(status, dict):
        return (
            "the console is enabled but the Tailscale Funnel state could not be determined, "
            "so it cannot be confirmed that port {} is private".format(listen_port)
        )
    if listen_port in funnel_exposed_local_ports(status):
        return (
            f"the console is enabled on port {listen_port}, which Tailscale Funnel publishes "
            "to the public internet. The console writes files and starts processes; it must "
            "listen on a tailnet-only port (`tailscale serve`), not the Funnel."
        )
    return None


def console_paths():
    """The ingest modules the console calls, plus the paths it should call them with.

    The import is **lazy on purpose**. The family dashboard is a read-only surface that has to
    keep serving even if the ingest tree cannot be imported, so an ingest-side breakage must
    not be able to stop this server from starting. `bin/` is also not a package, so the repo
    root has to reach `sys.path` before `ingest` is importable at all.
    """
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    from ingest import queue as ingest_queue
    from ingest import review as ingest_review
    from ingest import upload as ingest_upload

    return SimpleNamespace(
        upload=ingest_upload,
        queue=ingest_queue,
        review=ingest_review,
        inbox=Path(CONSOLE_INBOX_DIR or ingest_queue.INBOX_DIR),
        queue_dir=Path(CONSOLE_QUEUE_DIR or ingest_queue.QUEUE_DIR),
        manifest=Path(CONSOLE_MANIFEST_PATH or ingest_review.MANIFEST_PATH),
    )


class GatedHandler(SimpleHTTPRequestHandler):
    """Static file server with a Basic-Auth gate and a /v1/* conductor proxy."""

    # --- auth ---------------------------------------------------------------
    def _authed(self) -> bool:
        if not PASSWORD:
            return True  # open mode (guarded at startup)
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
        except Exception:
            return False
        _user, _, supplied = decoded.partition(":")
        # Constant-time compare; username is ignored, the password is the secret.
        return hmac.compare_digest(supplied, PASSWORD)

    def _challenge(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", f'Basic realm="{REALM}", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "13")
        self.end_headers()
        self.wfile.write(b"Unauthorized\n")

    def _gate(self) -> bool:
        if self._authed():
            return True
        self._challenge()
        return False

    # --- conductor proxy ----------------------------------------------------
    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        target = CONDUCTOR_URL + self.path  # self.path includes /v1/... + query
        req = urllib.request.Request(target, data=body, method=method)
        ctype = self.headers.get("Content-Type")
        if ctype:
            req.add_header("Content-Type", ctype)
        accept = self.headers.get("Accept")
        if accept:
            req.add_header("Accept", accept)
        try:
            upstream = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as exc:
            # Surface the conductor's own status + body to the dashboard.
            payload = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        except Exception as exc:  # conductor down / unreachable
            msg = (f'{{"error":{{"message":"conductor unreachable at '
                   f'{CONDUCTOR_URL}: {exc}"}}}}').encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return

        # Stream the response through so SSE chat completions arrive token-by-token.
        self.send_response(upstream.status)
        for key, val in upstream.headers.items():
            if key.lower() in _HOP_BY_HOP or key.lower() == "content-length":
                continue
            self.send_header(key, val)
        self.end_headers()
        try:
            while True:
                chunk = upstream.read(2048)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client navigated away mid-stream
        finally:
            upstream.close()

    # --- operator console ----------------------------------------------------
    def _console_route(self) -> str | None:
        path = self.path.split("?", 1)[0]
        if path == "/console" or path.startswith("/console/"):
            return path.rstrip("/") or "/console"
        return None

    def _send_bytes(self, status: int, ctype: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _console_static_withheld(self) -> bool:
        """True when the request is for a console asset the disabled console must not expose."""
        if CONSOLE_ENABLED:
            return False
        if self.path.split("?", 1)[0] not in CONSOLE_STATIC_PATHS:
            return False
        self.send_error(404, "Not Found")
        return True

    def _send_json(self, status: int, payload) -> None:
        body = (json.dumps(payload) + "\n").encode()
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _refuse(self, status: int, message: str) -> None:
        """Answer with a reason the console page can show the operator verbatim."""
        self._send_json(status, {"error": message})

    def _console_page(self) -> None:
        page = os.path.join(self.directory, "console.html")
        if not os.path.isfile(page):
            self.send_error(404, "console.html not found")
            return
        with open(page, "rb") as handle:
            self._send_bytes(200, "text/html; charset=utf-8", handle.read())

    def _console_health(self) -> None:
        self._send_json(200, {"console": "enabled", "routes": list(CONSOLE_ROUTES)})

    def _read_json_object(self) -> dict | None:
        """The request body as a JSON object, or None once the refusal has been sent."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_JSON_BYTES:
            self.close_connection = True  # the body was never read; this connection is spent
            self._refuse(413, f"request body is over the {MAX_JSON_BYTES}-byte limit")
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"")
        except ValueError:
            self._refuse(400, "body is not valid JSON")
            return None
        if not isinstance(payload, dict):
            self._refuse(400, "body must be a JSON object")
            return None
        return payload

    def _console_queue(self) -> None:
        paths = console_paths()
        self._send_json(200, paths.review.queue_view(paths.queue.load_queue(paths.queue_dir)))

    def _console_review(self) -> None:
        payload = self._read_json_object()
        if payload is None:
            return

        item_id = payload.get("id", "")
        if not isinstance(item_id, str) or not item_id:
            self._refuse(400, "a review needs the item's 'id'")
            return
        decision = payload.get("decision", "")
        if not isinstance(decision, str):
            self._refuse(400, "'decision' must be a string")
            return
        reason = payload.get("reason", "")
        if not isinstance(reason, str):
            self._refuse(400, "'reason' must be a string")
            return
        fields = payload.get("fields") or {}
        if not isinstance(fields, dict):
            # edit_item() calls .items() on this. A string would raise AttributeError rather
            # than ReviewError, which reaches the operator as a 500 and a traceback.
            self._refuse(400, "'fields' must be a JSON object")
            return

        paths = console_paths()
        try:
            view = paths.review.apply_decision(
                item_id,
                decision,
                fields=fields,
                reason=reason,
                queue_dir=paths.queue_dir,
                manifest_path=paths.manifest,
            )
        except paths.review.UnknownItem as exc:
            self._refuse(404, str(exc))
            return
        except paths.review.ReviewError as exc:
            # Every other refusal — an unknown verb, an already-decided item, a value outside
            # its vocabulary — happens before apply_decision writes anything.
            self._refuse(400, str(exc))
            return
        self._send_json(200, view)

    def _console_upload(self) -> None:
        paths = console_paths()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        filename = (query.get("filename") or [""])[0]
        if not filename:
            self._refuse(400, "an upload needs a ?filename= parameter")
            return

        cap = paths.upload.MAX_UPLOAD_BYTES
        declared = int(self.headers.get("Content-Length", 0) or 0)
        if declared > cap:
            # The module caps len(data), which is the rule that counts — a Content-Length is a
            # claim and the payload is the fact. But that check can only speak once the bytes
            # are already in memory, and this server shares a Mac mini with everything else,
            # so an oversize *claim* is refused here before the body is read.
            self.close_connection = True
            self._refuse(413, f"upload declares {declared} bytes, over the {cap}-byte cap")
            return

        data = self.rfile.read(declared) if declared else b""
        try:
            written = paths.upload.stage_upload(filename, data, inbox=paths.inbox)
        except paths.upload.UploadRejected as exc:
            self._refuse(400, str(exc))
            return
        # The final name only, never the server path. A collision renames the file, and that
        # rename is the one thing about the write the operator has to be told.
        self._send_json(200, {"filename": written.name})

    def _console(self, route: str, method: str) -> None:
        if not CONSOLE_ENABLED:
            self.send_error(404, "Not Found")
            return
        routes = {
            "/console": {"GET": self._console_page},
            "/console/api/health": {"GET": self._console_health},
            "/console/api/queue": {"GET": self._console_queue},
            "/console/api/review": {"POST": self._console_review},
            "/console/api/upload": {"POST": self._console_upload},
        }
        by_method = routes.get(route)
        if by_method is None:
            self.send_error(404, "Not Found")
            return
        handler = by_method.get(method)
        if handler is None:
            self.send_error(405, "Method Not Allowed")
            return
        handler()

    # --- HTTP verbs ---------------------------------------------------------
    def do_GET(self) -> None:
        if not self._gate():
            return
        route = self._console_route()
        if route is not None:
            self._console(route, "GET")
            return
        if self.path.startswith("/v1/"):
            self._proxy("GET")
            return
        if self._console_static_withheld():
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if not self._gate():
            return
        if self._console_static_withheld():
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if not self._gate():
            return
        route = self._console_route()
        if route is not None:
            self._console(route, "POST")
            return
        if self.path.startswith("/v1/"):
            self._proxy("POST")
            return
        self.send_error(405, "Method Not Allowed")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[serve_dashboard] %s - %s\n" % (self.address_string(), fmt % args))


def _serve_forever(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    if not PASSWORD and os.environ.get("DIGITAL_DAD_ALLOW_OPEN") != "1":
        sys.stderr.write(
            "REFUSING TO START: DIGITAL_DAD_DASHBOARD_PASSWORD is unset, which would serve "
            "the dashboard with NO authentication. Set the password, or set "
            "DIGITAL_DAD_ALLOW_OPEN=1 to override for trusted local use.\n"
        )
        return 1
    if CONSOLE_ENABLED:
        refusal = console_refusal_reason(PORT, *probe_funnel())
        if refusal:
            sys.stderr.write(f"REFUSING TO START: {refusal}\n")
            return 1
    if not os.path.isdir(DASHBOARD_DIR):
        sys.stderr.write(f"ERROR: dashboard dir not found: {DASHBOARD_DIR}\n")
        return 1
    if not os.path.isfile(os.path.join(DASHBOARD_DIR, "index.html")):
        sys.stderr.write(
            f"WARNING: no index.html in {DASHBOARD_DIR} — run `make dashboard` first.\n"
        )

    handler = partial(GatedHandler, directory=DASHBOARD_DIR)
    server = ThreadingHTTPServer((ADDRESS, PORT), handler)
    gate = "PASSWORD-GATED" if PASSWORD else "OPEN (no password!)"
    sys.stderr.write(
        f"[serve_dashboard] serving {DASHBOARD_DIR} on http://{ADDRESS}:{PORT} "
        f"[{gate}], proxying /v1/* → {CONDUCTOR_URL}\n"
    )
    _serve_forever(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
