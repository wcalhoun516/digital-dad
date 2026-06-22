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
import os
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get("DIGITAL_DAD_DASHBOARD_PASSWORD", "")
PORT = int(os.environ.get("DIGITAL_DAD_SHARE_PORT", "8000"))
ADDRESS = os.environ.get("DIGITAL_DAD_SHARE_ADDRESS", "127.0.0.1")
CONDUCTOR_URL = os.environ.get("DIGITAL_DAD_CONDUCTOR_URL", "http://127.0.0.1:8080").rstrip("/")
REALM = "digital-dad dashboard"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_DIR = os.environ.get("DIGITAL_DAD_DASHBOARD_DIR", os.path.join(_REPO_ROOT, "dashboard"))

# Hop-by-hop headers must not be forwarded through a proxy (RFC 7230 §6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


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

    # --- HTTP verbs ---------------------------------------------------------
    def do_GET(self) -> None:
        if not self._gate():
            return
        if self.path.startswith("/v1/"):
            self._proxy("GET")
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if not self._gate():
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if not self._gate():
            return
        if self.path.startswith("/v1/"):
            self._proxy("POST")
            return
        self.send_error(405, "Method Not Allowed")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[serve_dashboard] %s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    if not PASSWORD and os.environ.get("DIGITAL_DAD_ALLOW_OPEN") != "1":
        sys.stderr.write(
            "REFUSING TO START: DIGITAL_DAD_DASHBOARD_PASSWORD is unset, which would serve "
            "the dashboard with NO authentication. Set the password, or set "
            "DIGITAL_DAD_ALLOW_OPEN=1 to override for trusted local use.\n"
        )
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
