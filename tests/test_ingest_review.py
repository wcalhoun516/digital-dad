"""Tests for the ingest review CLI (roadmap #31)."""

import json

import pytest

from ingest.queue import save_item
from ingest.review import (
    InvalidEdit,
    accept_item,
    edit_item,
    item_view,
    queue_summary,
    queue_view,
    reject_item,
    run_cli,
)


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


class TestEditItem:
    def test_applies_a_corrected_title(self):
        item = _item()
        edit_item(item, {"title": "Real Title"})
        assert item["meta"]["title"] == "Real Title"

    def test_accepts_a_value_from_the_vocabulary(self):
        item = _item()
        edit_item(item, {"modality": "book"})
        assert item["meta"]["modality"] == "book"

    def test_a_hand_entered_date_is_approximate_never_exact(self):
        item = _item()
        edit_item(item, {"date": "1998-04-01"})
        assert item["meta"]["date"] == "1998-04-01"
        assert item["meta"]["date_confidence"] == "approximate"

    def test_blank_keeps_the_current_value(self):
        item = _item()
        edit_item(item, {"title": ""})
        assert item["meta"]["title"] == "A"

    def test_a_value_outside_the_vocabulary_is_refused(self):
        item = _item()
        with pytest.raises(InvalidEdit) as excinfo:
            edit_item(item, {"privacy": "pubic"})
        assert "pubic" in str(excinfo.value)

    def test_a_refused_edit_changes_nothing(self):
        """Partial application would leave the item in a state no front end asked for."""
        item = _item()
        with pytest.raises(InvalidEdit):
            edit_item(item, {"title": "Real Title", "privacy": "pubic"})
        assert item["meta"]["title"] == "A"

    def test_a_field_the_reviewer_may_not_set_is_refused(self):
        item = _item()
        with pytest.raises(InvalidEdit):
            edit_item(item, {"license": "forbes"})

    def test_a_non_string_value_is_refused_not_crashed_on(self):
        """JSON from a console client can carry any type; a 500 is not an answer."""
        item = _item()
        for value in (7, None, ["Real Title"], {"title": "x"}):
            with pytest.raises(InvalidEdit):
                edit_item(item, {"title": value})

    def test_a_queue_field_cannot_be_smuggled_in_as_a_correction(self):
        """A console client must not be able to set status or rewrite the content hash."""
        item = _item()
        for field in ("status", "content_hash", "id"):
            with pytest.raises(InvalidEdit):
                edit_item(item, {field: "x"})
        assert item["status"] == "pending"
        assert item["content_hash"] == "1234abcd"


class TestItemView:
    def test_carries_the_warnings_and_the_guessed_metadata(self):
        item = _item()
        item["warnings"] = ["no date found"]
        view = item_view(item)
        assert view["warnings"] == ["no date found"]
        assert view["meta"]["modality"] == "letter"
        assert view["meta"]["privacy"] == "private"

    def test_previews_the_opening_not_the_whole_document(self):
        item = _item()
        item["documents"] = [{"title": "A", "text": "x" * 5000, "ordinal": 0}]
        view = item_view(item)
        assert view["preview"] == "x" * 400

    def test_never_carries_the_document_bodies(self):
        """A queue listing of a book would otherwise ship 80,000 words of private material."""
        item = _item()
        item["documents"] = [{"title": "A", "text": "SECRET" * 500, "ordinal": 0}]
        assert "SECRET" * 500 not in json.dumps(item_view(item))

    def test_reports_the_document_count_as_a_number(self):
        item = _item()
        item["documents"] = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        assert item_view(item)["documents"] == 3

    def test_an_item_with_no_documents_previews_empty(self):
        item = _item()
        item["documents"] = []
        assert item_view(item)["preview"] == ""

    def test_is_json_serialisable(self):
        """It is an HTTP response body before it is anything else."""
        assert json.loads(json.dumps(item_view(_item())))["id"] == "a-1234abcd"

    def test_carries_the_reject_reason_once_rejected(self):
        item = _item()
        reject_item(item, "bad scan")
        assert item_view(item)["reject_reason"] == "bad scan"


class TestQueueView:
    def test_lists_only_pending_items(self):
        items = [_item("a"), _item("b", "accepted"), _item("c", "rejected")]
        view = queue_view(items)
        assert [i["id"] for i in view["items"]] == ["a"]

    def test_reports_the_full_summary_alongside_the_pending_list(self):
        items = [_item("a"), _item("b", "accepted"), _item("c", "rejected")]
        assert queue_view(items)["summary"] == {
            "total": 3,
            "pending": 1,
            "accepted": 1,
            "rejected": 1,
        }

    def test_an_empty_queue_is_an_empty_list_not_an_error(self):
        assert queue_view([]) == {
            "summary": {"total": 0, "pending": 0, "accepted": 0, "rejected": 0},
            "items": [],
        }


class TestRejectItem:
    def test_marks_the_item_rejected_with_its_reason(self):
        item = _item()
        reject_item(item, "bad scan")
        assert item["status"] == "rejected"
        assert item["reject_reason"] == "bad scan"

    def test_a_blank_reason_is_refused(self):
        """A reject with no reason is unrecoverable later — the plan requires the why."""
        item = _item()
        for reason in ("", "   "):
            with pytest.raises(InvalidEdit):
                reject_item(item, reason)
        assert item["status"] == "pending"

    def test_a_non_string_reason_is_refused(self):
        item = _item()
        with pytest.raises(InvalidEdit):
            reject_item(item, None)
        assert item["status"] == "pending"

    def test_the_documents_are_kept_not_deleted(self):
        """Rejects are never destroyed — a bad extraction must stay recoverable."""
        item = _item()
        reject_item(item, "bad scan")
        assert item["documents"] == [{"title": "A", "text": "body", "ordinal": 0}]


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
