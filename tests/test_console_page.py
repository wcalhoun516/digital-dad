"""The operator console page, against the real server (plan 0011 steps 2-3, front end).

Two layers, mirroring `tests/test_dashboard_corpus_controls.py`:

  * **live** — the real `dashboard/console.html` served by the real `bin/serve_dashboard.py`,
    driven in headless Chromium through the Basic-Auth gate, writing into a tmp inbox and
    queue. This is the only layer that proves the page and the routes actually compose: a
    file chosen in a file input ends up on disk, and an Accept click ends up in the manifest.
    SKIPs cleanly when Chromium is unavailable, so CI stays green.
  * **structural** — CI-safe string checks pinning the things a future edit would break
    silently: that the page calls all three routes, and that it never assigns innerHTML.
"""

import importlib.util
import json
import re
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ingest.queue import save_item

ROOT = Path(__file__).resolve().parent.parent
CONSOLE_HTML = ROOT / "dashboard" / "console.html"
SERVER_PY = ROOT / "bin" / "serve_dashboard.py"
PASSWORD = "correct-horse"


def _item(item_id="letter-1234abcd", title="A Letter Home"):
    return {
        "id": item_id,
        "status": "pending",
        "original": "data/inbox/letter.md",
        "content_hash": "1234abcd",
        "documents": [{"title": title, "text": "Dear Will, the markets are mad.", "ordinal": 0}],
        "meta": {
            "title": title,
            "date": "",
            "date_confidence": "unknown",
            "modality": "letter",
            "authorship": "george",
            "privacy": "private",
            "license": "personal",
        },
        "confidence": 0.75,
        "warnings": ["no date found"],
        "staged_at": "2026-09-20T00:00:00+00:00",
    }


# --- structural ------------------------------------------------------------------------


class TestPageStructure:
    def test_the_page_calls_every_route_it_depends_on(self):
        source = CONSOLE_HTML.read_text(encoding="utf-8")
        for route in ("/console/api/health", "/console/api/upload", "/console/api/queue",
                      "/console/api/review"):
            assert route in source, f"the console page never calls {route}"

    def test_the_page_never_assigns_innerhtml(self):
        """Titles, warnings and previews are text out of an uploaded file. Treating any of it
        as markup would let a dropped document run script in the operator's browser."""
        source = CONSOLE_HTML.read_text(encoding="utf-8")
        # Matched against real use, not prose: the comment explaining this rule says the word.
        assert not re.search(r"\.innerHTML\s*=", source)
        assert ".insertAdjacentHTML(" not in source
        assert "document.write(" not in source


# --- live ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    manager = api.sync_playwright().start()
    try:
        launched = manager.chromium.launch()
    except Exception as exc:  # chromium not installed / can't launch
        manager.stop()
        pytest.skip(f"headless Chromium unavailable: {str(exc).splitlines()[0]}")
    yield launched
    launched.close()
    manager.stop()


@pytest.fixture
def live(tmp_path):
    """The real console.html on the real server, writing only inside tmp_path."""
    spec = importlib.util.spec_from_file_location("_serve_dashboard_page_under_test", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    inbox, queue_dir = tmp_path / "inbox", tmp_path / "queue"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"last_updated": "", "total_articles": 0, "articles": []}))

    module.PASSWORD = PASSWORD
    module.CONSOLE_ENABLED = True
    module.CONSOLE_INBOX_DIR = inbox
    module.CONSOLE_QUEUE_DIR = queue_dir
    module.CONSOLE_MANIFEST_PATH = manifest
    module.CONSOLE_STATE_PATH = tmp_path / "console" / "job.json"

    handler = partial(module.GatedHandler, directory=str(CONSOLE_HTML.parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Live:
        base = f"http://127.0.0.1:{server.server_port}"
        inbox_dir = inbox
        queue = queue_dir
        manifest_path = manifest
        state_path = module.CONSOLE_STATE_PATH

        def stage(self, item):
            save_item(item, queue_dir)
            return item

    try:
        yield Live()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def page(browser, live):
    context = browser.new_context(
        http_credentials={"username": "operator", "password": PASSWORD}
    )
    opened = context.new_page()
    opened.errors = []
    opened.on("pageerror", lambda exc: opened.errors.append(str(exc)))
    yield opened
    context.close()


def _open(page, live):
    page.goto(live.base + "/console", wait_until="networkidle")
    return page


class TestLiveConsole:
    def test_the_page_loads_clean_and_reports_the_console_enabled(self, page, live):
        _open(page, live)
        assert page.errors == []
        assert "console enabled" in page.text_content("#status-text")
        assert page.get_attribute("#dot", "class") == "dot ok"

    def test_an_empty_queue_says_so(self, page, live):
        _open(page, live)
        assert "Nothing pending" in page.text_content("#queue")

    def test_a_pending_item_renders_its_warning_metadata_and_preview(self, page, live):
        live.stage(_item())
        _open(page, live)
        queue_text = page.text_content("#queue")
        assert "letter-1234abcd" in queue_text
        assert "no date found" in queue_text
        assert "the markets are mad" in queue_text
        assert page.input_value("#queue input[data-field=title]") == "A Letter Home"
        assert "1 item(s) — 1 pending" in page.text_content("#queue-summary")

    def test_uploading_a_file_puts_it_in_the_inbox(self, page, live, tmp_path):
        source = tmp_path / "chosen.md"
        source.write_text("# A Letter\n\nDear Will,\n", encoding="utf-8")
        _open(page, live)
        page.set_input_files("#files", str(source))
        page.click("#upload-btn")
        page.wait_for_selector("#upload-results li.ok")
        assert (live.inbox_dir / "chosen.md").read_text() == "# A Letter\n\nDear Will,\n"
        assert page.errors == []

    def test_a_refused_upload_shows_the_servers_reason(self, page, live, tmp_path):
        source = tmp_path / "payload.exe"
        source.write_bytes(b"MZ" * 32)
        _open(page, live)
        page.set_input_files("#files", str(source))
        page.click("#upload-btn")
        page.wait_for_selector("#upload-results li.bad")
        assert "no ingest handler" in page.text_content("#upload-results")
        assert list(live.inbox_dir.glob("*")) == [] if live.inbox_dir.exists() else True

    def test_accepting_in_the_browser_writes_the_manifest_and_clears_the_queue(self, page, live):
        live.stage(_item())
        _open(page, live)
        page.click("#queue button.accept")
        page.wait_for_function("document.querySelector('#queue').textContent.includes('Nothing')")
        manifest = json.loads(live.manifest_path.read_text())
        assert [a["slug"] for a in manifest["articles"]] == ["letter-1234abcd"]
        assert manifest["articles"][0]["title"] == "A Letter Home"
        assert page.errors == []

    def test_a_correction_typed_in_the_browser_reaches_the_manifest(self, page, live):
        live.stage(_item())
        _open(page, live)
        page.fill("#queue input[data-field=title]", "The Real Title")
        page.click("#queue button.accept")
        page.wait_for_function("document.querySelector('#queue').textContent.includes('Nothing')")
        manifest = json.loads(live.manifest_path.read_text())
        assert manifest["articles"][0]["title"] == "The Real Title"

    def test_accepting_an_untouched_date_does_not_downgrade_its_confidence(self, page, live):
        """`edit_item` stamps every date it accepts as `approximate`. If the page resent the
        date field just because it was displayed, a plain Accept would quietly demote a date
        the extractor was sure about."""
        item = _item()
        item["meta"]["date"] = "1994-06-01"
        item["meta"]["date_confidence"] = "exact"
        live.stage(item)
        _open(page, live)
        page.click("#queue button.accept")
        page.wait_for_function("document.querySelector('#queue').textContent.includes('Nothing')")
        saved = json.loads((live.queue / "letter-1234abcd.json").read_text())
        assert saved["meta"]["date_confidence"] == "exact"
        assert saved["meta"]["date"] == "1994-06-01"

    def test_a_rejected_item_keeps_its_reason_and_is_not_deleted(self, page, live):
        live.stage(_item())
        _open(page, live)
        page.on("dialog", lambda dialog: dialog.accept("OCR garbage"))
        page.click("#queue button.reject")
        page.wait_for_function("document.querySelector('#queue').textContent.includes('Nothing')")
        saved = json.loads((live.queue / "letter-1234abcd.json").read_text())
        assert saved["status"] == "rejected"
        assert saved["reject_reason"] == "OCR garbage"

    def test_extracted_text_is_rendered_as_text_never_as_markup(self, page, live):
        """An uploaded document controls this string. If it were ever treated as markup, the
        operator's browser would run it — with the dashboard password already in the session.
        """
        hostile = '<img src=x onerror="window.__pwned=1">'
        item = _item(title=hostile)
        item["documents"][0]["text"] = hostile
        item["warnings"] = [hostile]
        live.stage(item)
        _open(page, live)
        assert page.evaluate("window.__pwned === undefined") is True
        assert page.query_selector("#queue img") is None
        assert hostile in page.text_content("#queue")
        assert page.input_value("#queue input[data-field=title]") == hostile


# --- the job runner panel (step 4) -------------------------------------------------------


class TestJobPanelStructure:
    def test_the_page_calls_the_job_routes(self):
        source = CONSOLE_HTML.read_text(encoding="utf-8")
        assert "/console/api/job" in source
        assert "/console/api/job/log" in source

    def test_the_page_no_longer_tells_the_operator_to_go_to_a_terminal(self):
        """Step 4 *is* that button. A note pointing at `make ingest` would now be a lie."""
        source = CONSOLE_HTML.read_text(encoding="utf-8")
        assert "until step 4 lands" not in source
        assert "at a terminal" not in source


@pytest.fixture
def zen(monkeypatch):
    """A throwaway job that prints and exits, so no registered pipeline step is ever run."""
    from console import jobs

    monkeypatch.setitem(jobs.JOBS, "zen", jobs.JobSpec(("-m", "this"), "prints the Zen"))
    return jobs


class TestLiveJobPanel:
    def test_the_panel_lists_the_registered_jobs_with_their_summaries(self, page, live):
        _open(page, live)
        assert page.query_selector("#jobs button[data-job=ingest]") is not None
        assert "review queue" in page.text_content("#jobs")
        assert page.errors == []

    def test_running_a_job_streams_its_log_and_reports_success(self, page, live, zen):
        _open(page, live)
        page.click("#jobs button[data-job=zen]")
        page.wait_for_function(
            "document.querySelector('#job-state').textContent.includes('succeeded')",
            timeout=15000,
        )
        assert "Beautiful is better than ugly" in page.text_content("#job-log")
        assert page.errors == []

    def test_an_expensive_job_is_not_started_until_the_operator_confirms(self, page, live,
                                                                        monkeypatch):
        """Dismissing the prompt must mean nothing ran — an hour of GPU is not an undo."""
        from console import jobs

        monkeypatch.setitem(
            jobs.JOBS, "pricey", jobs.JobSpec(("-m", "this"), "costs something", costly=True)
        )
        _open(page, live)
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.click("#jobs button[data-job=pricey]")
        page.wait_for_timeout(500)
        assert "idle" in page.text_content("#job-state")

    def test_a_busy_runner_says_what_is_holding_it(self, page, live):
        import os

        state_path = live.state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "job": "train", "state": "running", "pid": os.getpid(), "exit_code": None,
            "started_at": "2026-09-21T00:00:00+00:00", "finished_at": None, "log": "x.log",
        }), encoding="utf-8")
        _open(page, live)
        assert "train" in page.text_content("#job-state")
        assert "running" in page.text_content("#job-state")
