"""Tests for the ingest review CLI (roadmap #31)."""

import json

import pytest

from ingest.queue import load_queue, save_item, scan_inbox
from ingest.review import (
    InvalidDecision,
    InvalidEdit,
    ReviewError,
    UnknownItem,
    accept_item,
    apply_decision,
    edit_item,
    item_view,
    print_report,
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


class TestEndToEnd:
    """A real file through the real arc: inbox → queue → console payload → manifest."""

    def test_a_dropped_file_becomes_a_corpus_entry_through_apply_decision(self, tmp_path):
        inbox, queue = tmp_path / "inbox", tmp_path / "queue"
        inbox.mkdir()
        (inbox / "letter.md").write_text("# A Letter Home\n\nDear Will,\n\nLove, Dad\n")
        manifest_path = _empty_manifest(tmp_path)

        assert scan_inbox(inbox, queue)["staged"] == 1

        listing = queue_view(load_queue(queue))
        assert listing["summary"]["pending"] == 1
        (pending,) = listing["items"]
        assert pending["meta"]["title"] == "A Letter Home"
        assert "Dear Will" in pending["preview"]

        view = apply_decision(
            pending["id"],
            "accept",
            fields={"modality": "letter", "date": "1998-04-01"},
            queue_dir=queue,
            manifest_path=manifest_path,
        )

        assert view["status"] == "accepted"
        (entry,) = json.loads(manifest_path.read_text())["articles"]
        assert entry["title"] == "A Letter Home"
        assert entry["date"] == "1998-04-01"
        assert entry["provenance"]["modality"] == "letter"
        # Ingested material is private until a human says otherwise.
        assert entry["provenance"]["privacy"] == "private"
        assert entry["provenance"]["date_confidence"] == "approximate"

    def test_the_accepted_item_drops_out_of_the_pending_listing(self, tmp_path):
        inbox, queue = tmp_path / "inbox", tmp_path / "queue"
        inbox.mkdir()
        (inbox / "letter.md").write_text("# A Letter Home\n\nDear Will,\n")
        manifest_path = _empty_manifest(tmp_path)
        scan_inbox(inbox, queue)

        item_id = queue_view(load_queue(queue))["items"][0]["id"]
        apply_decision(
            item_id, "accept", queue_dir=queue, manifest_path=manifest_path
        )

        listing = queue_view(load_queue(queue))
        assert listing["items"] == []
        assert listing["summary"] == {
            "total": 1,
            "pending": 0,
            "accepted": 1,
            "rejected": 0,
        }


class TestPrintReport:
    def test_lists_only_what_still_needs_a_decision(self, capsys):
        print_report([_item("still-pending"), _item("already-done", "accepted")])
        out = capsys.readouterr().out
        assert "still-pending" in out
        assert "already-done" not in out


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


class TestApplyDecision:
    """The one entry point both front ends call. A console route adds HTTP, not logic."""

    def _queue(self, tmp_path, item=None):
        queue = tmp_path / "queue"
        save_item(item or _item(), queue)
        return queue, _empty_manifest(tmp_path)

    def test_accept_appends_to_the_manifest_and_persists_the_item(self, tmp_path):
        queue, manifest_path = self._queue(tmp_path)

        view = apply_decision(
            "a-1234abcd", "accept", queue_dir=queue, manifest_path=manifest_path
        )

        assert view["status"] == "accepted"
        assert len(json.loads(manifest_path.read_text())["articles"]) == 1
        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "accepted"

    def test_reject_persists_the_reason_and_leaves_the_manifest_alone(self, tmp_path):
        queue, manifest_path = self._queue(tmp_path)

        apply_decision(
            "a-1234abcd",
            "reject",
            reason="bad scan",
            queue_dir=queue,
            manifest_path=manifest_path,
        )

        stored = json.loads((queue / "a-1234abcd.json").read_text())
        assert stored["status"] == "rejected"
        assert stored["reject_reason"] == "bad scan"
        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_edit_corrects_the_metadata_and_leaves_the_item_pending(self, tmp_path):
        queue, manifest_path = self._queue(tmp_path)

        view = apply_decision(
            "a-1234abcd",
            "edit",
            fields={"title": "Real Title"},
            queue_dir=queue,
            manifest_path=manifest_path,
        )

        assert view["status"] == "pending"
        assert json.loads((queue / "a-1234abcd.json").read_text())["meta"]["title"] == (
            "Real Title"
        )
        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_accept_applies_corrections_in_the_same_call(self, tmp_path):
        queue, manifest_path = self._queue(tmp_path)

        apply_decision(
            "a-1234abcd",
            "accept",
            fields={"title": "Real Title", "privacy": "public"},
            queue_dir=queue,
            manifest_path=manifest_path,
        )

        entry = json.loads(manifest_path.read_text())["articles"][0]
        assert entry["title"] == "Real Title"
        assert entry["provenance"]["privacy"] == "public"

    def test_an_already_decided_item_is_refused(self, tmp_path):
        """Without this, POSTing accept twice files the same document in the corpus twice."""
        queue, manifest_path = self._queue(tmp_path)
        apply_decision(
            "a-1234abcd", "accept", queue_dir=queue, manifest_path=manifest_path
        )

        with pytest.raises(InvalidDecision):
            apply_decision(
                "a-1234abcd", "accept", queue_dir=queue, manifest_path=manifest_path
            )

        assert len(json.loads(manifest_path.read_text())["articles"]) == 1

    def test_an_unknown_id_is_distinguishable_from_a_bad_decision(self, tmp_path):
        """A route answers 404 for one and 400 for the other; one exception cannot say both."""
        queue, manifest_path = self._queue(tmp_path)

        with pytest.raises(UnknownItem):
            apply_decision(
                "nope", "accept", queue_dir=queue, manifest_path=manifest_path
            )

    def test_an_unknown_verb_is_refused(self, tmp_path):
        queue, manifest_path = self._queue(tmp_path)

        with pytest.raises(InvalidDecision):
            apply_decision(
                "a-1234abcd", "delete", queue_dir=queue, manifest_path=manifest_path
            )

    def test_a_refused_correction_leaves_nothing_written(self, tmp_path):
        """An accept that fails validation must not half-file the document."""
        queue, manifest_path = self._queue(tmp_path)

        with pytest.raises(InvalidEdit):
            apply_decision(
                "a-1234abcd",
                "accept",
                fields={"privacy": "pubic"},
                queue_dir=queue,
                manifest_path=manifest_path,
            )

        assert json.loads(manifest_path.read_text())["articles"] == []
        stored = json.loads((queue / "a-1234abcd.json").read_text())
        assert stored["status"] == "pending"
        assert stored["meta"]["privacy"] == "private"

    def test_every_refusal_is_catchable_as_one_error_type(self, tmp_path):
        """A route wants a single `except ReviewError` rather than a growing tuple."""
        assert issubclass(InvalidEdit, ReviewError)
        assert issubclass(InvalidDecision, ReviewError)
        assert issubclass(UnknownItem, ReviewError)


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

    def test_a_reject_with_no_reason_is_refused_and_reported(self, tmp_path, capsys):
        """The CLI must surface the refusal, not print a tick and count it as decided."""
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(["r", "", "q"]),
        )

        out = capsys.readouterr().out
        assert "a reject needs a reason" in out
        assert "✓" not in out
        assert "0 decision(s)" in out
        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "pending"

    def test_an_out_of_vocabulary_answer_keeps_the_current_value(self, tmp_path, capsys):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        # edit -> title kept blank, date blank, modality nonsense, then accept
        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(["e", "", "", "sonnet", "", "", "a"]),
        )

        assert "not valid" in capsys.readouterr().out
        entry = json.loads(manifest_path.read_text())["articles"][0]
        assert entry["provenance"]["modality"] == "letter"

    def test_corrections_survive_an_unrecognised_decision(self, tmp_path):
        """Typing a typo after carefully retyping a title should not discard the retyping."""
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = _empty_manifest(tmp_path)

        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(["e", "Real Title", "", "", "", "", "xyzzy"]),
        )

        stored = json.loads((queue / "a-1234abcd.json").read_text())
        assert stored["meta"]["title"] == "Real Title"
        assert stored["status"] == "pending"
        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_the_cli_and_the_api_reach_an_identical_result(self, tmp_path):
        """Plan 0011's criterion: one decision implementation, two front ends."""
        cli_queue, api_queue = tmp_path / "cli", tmp_path / "api"
        save_item(_item(), cli_queue)
        save_item(_item(), api_queue)
        cli_manifest = tmp_path / "cli-manifest.json"
        api_manifest = tmp_path / "api-manifest.json"
        empty = json.dumps({"last_updated": "", "total_articles": 0, "articles": []})
        cli_manifest.write_text(empty)
        api_manifest.write_text(empty)

        run_cli(
            queue_dir=cli_queue,
            manifest_path=cli_manifest,
            input_fn=_scripted(
                ["e", "Real Title", "1998-04-01", "book", "", "public", "a"]
            ),
        )
        apply_decision(
            "a-1234abcd",
            "accept",
            fields={
                "title": "Real Title",
                "date": "1998-04-01",
                "modality": "book",
                "privacy": "public",
            },
            queue_dir=api_queue,
            manifest_path=api_manifest,
        )

        assert json.loads(cli_manifest.read_text()) == json.loads(
            api_manifest.read_text()
        )
        assert json.loads((cli_queue / "a-1234abcd.json").read_text()) == json.loads(
            (api_queue / "a-1234abcd.json").read_text()
        )

    def test_empty_queue_returns_zero(self, tmp_path):
        manifest_path = _empty_manifest(tmp_path)
        assert run_cli(queue_dir=tmp_path / "queue", manifest_path=manifest_path) == 0
