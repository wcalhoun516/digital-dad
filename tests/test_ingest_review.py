"""Tests for the ingest review CLI (roadmap #31)."""

import json

from ingest.queue import save_item
from ingest.review import accept_item, queue_summary, run_cli


def _item(item_id="a-1234abcd", status="pending"):
    return {
        "id": item_id,
        "status": status,
        "original": "data/inbox/a.txt",
        "content_hash": "1234abcd",
        "documents": [{"title": "A", "text": "body", "ordinal": 0}],
        "meta": {
            "title": "A",
            "date": "",
            "date_confidence": "unknown",
            "modality": "letter",
            "authorship": "george",
            "privacy": "private",
            "license": "personal",
        },
        "confidence": 1.0,
        "warnings": [],
        "staged_at": "2026-08-13T00:00:00+00:00",
    }


def _scripted(answers):
    """An input() stand-in that replays a fixed list of answers."""
    it = iter(answers)

    def _fn(_prompt=""):
        return next(it, "q")

    return _fn


def _empty_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"last_updated": "", "total_articles": 0, "articles": []}))
    return path


class TestQueueSummary:
    def test_counts_by_status(self):
        items = [_item("a"), _item("b", "accepted"), _item("c", "rejected")]
        assert queue_summary(items) == {
            "total": 3,
            "pending": 1,
            "accepted": 1,
            "rejected": 1,
        }


class TestAcceptItem:
    def test_appends_a_manifest_entry_with_provenance(self):
        manifest = {"last_updated": "", "total_articles": 0, "articles": []}
        out = accept_item(_item(), manifest)
        assert len(out["articles"]) == 1
        prov = out["articles"][0]["provenance"]
        assert prov["modality"] == "letter"
        assert prov["privacy"] == "private"
        assert prov["acquisition"]["method"] == "ingest"

    def test_updates_total_articles(self):
        manifest = {"last_updated": "", "total_articles": 0, "articles": []}
        out = accept_item(_item(), manifest)
        assert out["total_articles"] == 1

    def test_marks_the_item_accepted(self):
        item = _item()
        accept_item(item, {"last_updated": "", "total_articles": 0, "articles": []})
        assert item["status"] == "accepted"


class TestRunCli:
    def test_accepting_writes_the_manifest_and_updates_the_item(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        rc = run_cli(
            queue_dir=queue, manifest_path=manifest_path, input_fn=_scripted(["a"])
        )

        assert rc == 0
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest["articles"]) == 1
        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "accepted"

    def test_rejecting_marks_rejected_and_leaves_manifest_alone(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(["r", "bad scan"]),
        )

        item = json.loads((queue / "a-1234abcd.json").read_text())
        assert item["status"] == "rejected"
        assert item["reject_reason"] == "bad scan"
        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_quitting_leaves_the_item_pending(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        run_cli(queue_dir=queue, manifest_path=manifest_path, input_fn=_scripted(["q"]))

        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "pending"

    def test_editing_then_accepting_records_the_correction(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        # edit -> title, date, modality, authorship, privacy -> then accept
        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(
                ["e", "Real Title", "1998-04-01", "book", "", "public", "a"]
            ),
        )

        entry = json.loads(manifest_path.read_text())["articles"][0]
        assert entry["title"] == "Real Title"
        assert entry["date"] == "1998-04-01"
        assert entry["provenance"]["modality"] == "book"
        assert entry["provenance"]["privacy"] == "public"
        # a hand-entered date is approximate, never "exact"
        assert entry["provenance"]["date_confidence"] == "approximate"

    def test_already_decided_items_are_not_reprompted(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item("done-1", status="accepted"), queue)
        manifest_path = _empty_manifest(tmp_path)

        run_cli(queue_dir=queue, manifest_path=manifest_path, input_fn=_scripted([]))

        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_empty_queue_returns_zero(self, tmp_path):
        manifest_path = _empty_manifest(tmp_path)
        assert run_cli(queue_dir=tmp_path / "queue", manifest_path=manifest_path) == 0
