"""The operator console's three write-side routes (plan 0011 steps 2 and 3).

These routes are deliberately **thin**: `ingest/upload.py` decides whether a client-supplied
file may become a path on disk (PR #96), and `ingest/review.py` decides what accepting an item
means (PR #97). Both are already tested at the module level. What is *not* covered there, and
is what this file exists for, is everything HTTP adds on top:

  * the size cap must hold **before** a body is read — the module caps `len(data)`, which is
    only reachable once the payload is already in memory;
  * a refusal must come back as a status code an operator's browser can act on, rather than a
    traceback and a 500;
  * a client-supplied field must not be able to reach `apply_decision` in a shape that raises
    something other than `ReviewError`.

Like `test_console_gate.py`, everything here drives a **real** `ThreadingHTTPServer` over a
real socket. A unit test calling the handler methods directly would prove nothing about
dispatch, and dispatch is half of what is being added.
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

from ingest.queue import save_item
from ingest.review import PREVIEW_CHARS
from ingest.upload import MAX_UPLOAD_BYTES

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "bin" / "serve_dashboard.py"
PASSWORD = "correct-horse"


def _load_server_module():
    """Import bin/serve_dashboard.py by path — bin/ is scripts, not an importable package."""
    spec = importlib.util.spec_from_file_location("_serve_dashboard_routes_under_test", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item(item_id="a-1234abcd", status="pending", title="A Letter Home"):
    return {
        "id": item_id,
        "status": status,
        "original": "data/inbox/a.txt",
        "content_hash": item_id.split("-")[-1],
        "documents": [{"title": title, "text": "Dear Will, " + "word " * 200, "ordinal": 0}],
        "meta": {
            "title": title,
            "date": "",
            "date_confidence": "unknown",
            "modality": "letter",
            "authorship": "george",
            "privacy": "private",
            "license": "personal",
        },
        "confidence": 0.8,
        "warnings": ["no date found"],
        "staged_at": "2026-09-20T00:00:00+00:00",
    }


def _inbox_names(console):
    """What the inbox holds. An inbox that was never created is no files, not an error."""
    if not console.inbox_dir.is_dir():
        return []
    return sorted(p.name for p in console.inbox_dir.iterdir())


@pytest.fixture
def console(tmp_path):
    """A live console server whose writes all land inside tmp_path.

    The three path attributes are the seam that keeps these tests off the real corpus. They
    default to the ingest modules' own constants, so nothing here restates the on-disk layout.
    """
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>family dashboard</html>", encoding="utf-8")
    (dashboard_dir / "console.html").write_text("<html>operator console</html>", encoding="utf-8")

    inbox = tmp_path / "inbox"
    queue_dir = tmp_path / "queue"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"last_updated": "", "total_articles": 0, "articles": []}))

    module = _load_server_module()
    module.PASSWORD = PASSWORD
    module.CONSOLE_ENABLED = True
    module.CONSOLE_INBOX_DIR = inbox
    module.CONSOLE_QUEUE_DIR = queue_dir
    module.CONSOLE_MANIFEST_PATH = manifest

    handler = partial(module.GatedHandler, directory=str(dashboard_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Console:
        base = f"http://127.0.0.1:{server.server_port}"
        mod = module
        inbox_dir = inbox
        queue = queue_dir
        manifest_path = manifest

        def request(self, path, *, method="GET", body=None, ctype=None, password=PASSWORD,
                    headers=None):
            """Return (status, body_bytes). A 4xx/5xx is a result here, not an exception."""
            req = urllib.request.Request(self.base + path, method=method, data=body)
            if password is not None:
                token = base64.b64encode(f"operator:{password}".encode()).decode()
                req.add_header("Authorization", f"Basic {token}")
            if ctype:
                req.add_header("Content-Type", ctype)
            for name, value in (headers or {}).items():
                req.add_header(name, value)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        def json_request(self, path, payload, *, method="POST", **kwargs):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            status, raw = self.request(
                path, method=method, body=body, ctype="application/json", **kwargs
            )
            try:
                return status, json.loads(raw)
            except ValueError:
                return status, raw

        def stage(self, item):
            save_item(item, queue_dir)
            return item

    try:
        yield Console()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- GET /console/api/queue -------------------------------------------------------------


class TestQueueRoute:
    def test_an_empty_queue_is_an_empty_list_not_an_error(self, console):
        status, payload = console.json_request("/console/api/queue", None, method="GET")
        assert status == 200
        assert payload["items"] == []
        assert payload["summary"]["total"] == 0

    def test_a_pending_item_is_listed_with_its_warnings_and_preview(self, console):
        console.stage(_item())
        status, payload = console.json_request("/console/api/queue", None, method="GET")
        assert status == 200
        assert [i["id"] for i in payload["items"]] == ["a-1234abcd"]
        entry = payload["items"][0]
        assert entry["warnings"] == ["no date found"]
        assert entry["preview"].startswith("Dear Will,")
        assert entry["meta"]["title"] == "A Letter Home"

    def test_the_listing_never_carries_document_bodies(self, console):
        """A book is tens of thousands of private words; a listing has no reason to ship them."""
        console.stage(_item())
        status, payload = console.json_request("/console/api/queue", None, method="GET")
        assert status == 200
        entry = payload["items"][0]
        assert entry["documents"] == 1, "expected a count, not the documents themselves"
        assert len(entry["preview"]) <= PREVIEW_CHARS
        assert "word word word" not in entry["preview"][PREVIEW_CHARS:]

    def test_decided_items_are_counted_but_not_listed(self, console):
        console.stage(_item("pending-1111aaaa"))
        console.stage(_item("done-2222bbbb", status="accepted"))
        status, payload = console.json_request("/console/api/queue", None, method="GET")
        assert [i["id"] for i in payload["items"]] == ["pending-1111aaaa"]
        assert payload["summary"] == {"total": 2, "pending": 1, "accepted": 1, "rejected": 0}

    def test_the_queue_route_refuses_a_post(self, console):
        status, _ = console.request("/console/api/queue", method="POST", body=b"{}")
        assert status == 405


# --- POST /console/api/review -----------------------------------------------------------


class TestReviewRoute:
    def test_accepting_through_the_api_writes_the_manifest_entry(self, console):
        console.stage(_item())
        status, payload = console.json_request(
            "/console/api/review", {"id": "a-1234abcd", "decision": "accept"}
        )
        assert status == 200
        assert payload["status"] == "accepted"
        manifest = json.loads(console.manifest_path.read_text())
        assert [a["slug"] for a in manifest["articles"]] == ["a-1234abcd"]
        assert manifest["total_articles"] == 1

    def test_a_correction_travels_with_the_decision(self, console):
        console.stage(_item())
        status, payload = console.json_request(
            "/console/api/review",
            {"id": "a-1234abcd", "decision": "accept", "fields": {"title": "Real Title"}},
        )
        assert status == 200
        assert payload["meta"]["title"] == "Real Title"
        manifest = json.loads(console.manifest_path.read_text())
        assert manifest["articles"][0]["title"] == "Real Title"

    def test_rejecting_keeps_the_item_and_its_reason(self, console):
        console.stage(_item())
        status, payload = console.json_request(
            "/console/api/review",
            {"id": "a-1234abcd", "decision": "reject", "reason": "OCR garbage"},
        )
        assert status == 200
        assert payload["status"] == "rejected"
        assert payload["reject_reason"] == "OCR garbage"
        assert (console.queue / "a-1234abcd.json").is_file(), "a reject is never deleted"

    def test_an_unknown_id_is_404(self, console):
        status, payload = console.json_request(
            "/console/api/review", {"id": "nope-0000", "decision": "accept"}
        )
        assert status == 404
        assert "nope-0000" in payload["error"]

    def test_an_unknown_decision_is_400(self, console):
        console.stage(_item())
        status, payload = console.json_request(
            "/console/api/review", {"id": "a-1234abcd", "decision": "burn"}
        )
        assert status == 400
        assert "error" in payload

    def test_a_second_decision_on_the_same_item_is_refused(self, console):
        """A repeated POST must not file the same document into the corpus twice."""
        console.stage(_item())
        first, _ = console.json_request(
            "/console/api/review", {"id": "a-1234abcd", "decision": "accept"}
        )
        second, payload = console.json_request(
            "/console/api/review", {"id": "a-1234abcd", "decision": "accept"}
        )
        assert (first, second) == (200, 400)
        manifest = json.loads(console.manifest_path.read_text())
        assert len(manifest["articles"]) == 1, "the retry appended a duplicate corpus entry"

    def test_a_reject_with_no_reason_is_400_and_changes_nothing(self, console):
        console.stage(_item())
        status, _ = console.json_request(
            "/console/api/review", {"id": "a-1234abcd", "decision": "reject"}
        )
        assert status == 400
        saved = json.loads((console.queue / "a-1234abcd.json").read_text())
        assert saved["status"] == "pending"

    def test_a_value_outside_its_vocabulary_is_400_and_changes_nothing(self, console):
        console.stage(_item())
        status, _ = console.json_request(
            "/console/api/review",
            {"id": "a-1234abcd", "decision": "accept", "fields": {"privacy": "world-readable"}},
        )
        assert status == 400
        saved = json.loads((console.queue / "a-1234abcd.json").read_text())
        assert saved["status"] == "pending"
        assert json.loads(console.manifest_path.read_text())["articles"] == []

    def test_a_non_object_fields_value_is_400_not_a_500(self, console):
        """`edit_item` calls `.items()` on this — a string would be an AttributeError, not a
        ReviewError, and an operator would get a traceback instead of a message."""
        console.stage(_item())
        status, payload = console.json_request(
            "/console/api/review",
            {"id": "a-1234abcd", "decision": "accept", "fields": "title"},
        )
        assert status == 400
        assert "error" in payload

    def test_a_malformed_body_is_400(self, console):
        status, _ = console.json_request("/console/api/review", b"{not json")
        assert status == 400

    def test_a_json_array_body_is_400(self, console):
        status, _ = console.json_request("/console/api/review", [1, 2, 3])
        assert status == 400

    def test_a_missing_id_is_400(self, console):
        status, _ = console.json_request("/console/api/review", {"decision": "accept"})
        assert status == 400

    def test_the_review_route_refuses_a_get(self, console):
        status, _ = console.request("/console/api/review", method="GET")
        assert status == 405


# --- POST /console/api/upload -----------------------------------------------------------


class TestUploadRoute:
    def test_an_allowed_file_lands_in_the_inbox(self, console):
        status, payload = console.request(
            "/console/api/upload?filename=letter.md",
            method="POST",
            body=b"# A Letter\n\nDear Will,\n",
            ctype="application/octet-stream",
        )
        assert status == 200
        assert json.loads(payload)["filename"] == "letter.md"
        assert (console.inbox_dir / "letter.md").read_bytes() == b"# A Letter\n\nDear Will,\n"

    def test_a_traversal_attempt_is_refused_and_writes_nothing(self, console):
        for name in ("../escape.md", "..%2Fescape.md", "/etc/passwd.md", "a%00b.md", "a%2Fb.md"):
            status, payload = console.request(
                f"/console/api/upload?filename={name}", method="POST", body=b"x" * 32
            )
            assert status == 400, f"{name} was accepted"
            assert b"error" in payload
        assert _inbox_names(console) == []
        assert not (ROOT / "escape.md").exists()

    def test_an_unregistered_extension_is_refused(self, console):
        status, payload = console.request(
            "/console/api/upload?filename=payload.exe", method="POST", body=b"MZ" * 16
        )
        assert status == 400
        assert b"handler" in payload

    def test_a_missing_filename_is_400(self, console):
        status, _ = console.request("/console/api/upload", method="POST", body=b"x" * 32)
        assert status == 400

    def test_an_empty_upload_is_refused(self, console):
        status, _ = console.request(
            "/console/api/upload?filename=empty.md", method="POST", body=b""
        )
        assert status == 400

    def test_an_oversize_upload_is_refused_without_being_read(self, console):
        """The cap has to hold on the *header*, before the body is in memory.

        `stage_upload` caps `len(data)`, which is the right rule but only reachable once the
        payload has already been read. A 4 GB POST would be a memory exhaustion on the Mac
        mini before the module ever got a say, so the route refuses on the declared length
        first — and must not be *fooled* by a declared length either, which is why the
        payload cap stays where it is.
        """
        cap = MAX_UPLOAD_BYTES
        status, _ = console.request(
            "/console/api/upload?filename=huge.md",
            method="POST",
            body=b"x" * 64,
            headers={"Content-Length": str(cap + 1)},
        )
        assert status == 413
        assert _inbox_names(console) == []

    def test_a_colliding_name_is_written_alongside_never_over(self, console):
        console.inbox_dir.mkdir(parents=True, exist_ok=True)
        (console.inbox_dir / "letter.md").write_bytes(b"the original")
        status, payload = console.request(
            "/console/api/upload?filename=letter.md", method="POST", body=b"the second one"
        )
        assert status == 200
        assert json.loads(payload)["filename"] == "letter-1.md", "the operator must be told"
        assert (console.inbox_dir / "letter.md").read_bytes() == b"the original"
        assert (console.inbox_dir / "letter-1.md").read_bytes() == b"the second one"

    def test_the_response_never_leaks_the_server_path(self, console):
        status, payload = console.request(
            "/console/api/upload?filename=letter.md", method="POST", body=b"hello"
        )
        assert status == 200
        assert str(console.inbox_dir) not in payload.decode()

    def test_the_upload_route_refuses_a_get(self, console):
        status, _ = console.request("/console/api/upload?filename=letter.md", method="GET")
        assert status == 405


# --- the routes join the gate table -----------------------------------------------------


class TestRoutesAreGoverned:
    def test_all_three_routes_are_declared_in_the_route_table(self, console):
        """`CONSOLE_ROUTES` is what `test_console_gate.py` enumerates to prove every route
        401s unauthenticated. A route missing from it silently skips the auth tests."""
        for route in ("/console/api/upload", "/console/api/queue", "/console/api/review"):
            assert route in console.mod.CONSOLE_ROUTES, f"{route} is not in CONSOLE_ROUTES"

    def test_the_write_routes_401_without_the_password(self, console):
        cases = (
            ("/console/api/queue", "GET", None),
            ("/console/api/review", "POST", b"{}"),
            ("/console/api/upload?filename=letter.md", "POST", b"x" * 32),
        )
        for path, method, body in cases:
            status, _ = console.request(path, method=method, body=body, password=None)
            assert status == 401, f"{path} served without auth"

    def test_the_write_routes_404_when_the_console_is_disabled(self, console):
        console.mod.CONSOLE_ENABLED = False
        cases = (
            ("/console/api/queue", "GET", None),
            ("/console/api/review", "POST", b"{}"),
            ("/console/api/upload?filename=letter.md", "POST", b"x" * 32),
        )
        for path, method, body in cases:
            status, _ = console.request(path, method=method, body=body)
            assert status == 404, f"{path} responded while the console was disabled"
