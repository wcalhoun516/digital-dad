"""Tests for ingest queue staging (roadmap #30)."""

from ingest.queue import load_queue, scan_inbox, stage_file


def _inbox_with(tmp_path, name: str, text: str):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / name).write_text(text)
    return inbox


class TestStageFile:
    def test_staged_item_is_pending_with_content_hash(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        item = stage_file(inbox / "a.txt", queue)
        assert item["status"] == "pending"
        assert item["content_hash"]
        assert item["original"].endswith("a.txt")

    def test_staged_item_is_written_to_disk(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        stage_file(inbox / "a.txt", queue)
        assert len(list(queue.glob("*.json"))) == 1

    def test_unsupported_format_returns_none_and_stages_nothing(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "a.wav").write_bytes(b"\x00")
        queue = tmp_path / "queue"
        assert stage_file(inbox / "a.wav", queue) is None
        assert not list(queue.glob("*.json"))

    def test_restaging_the_same_content_is_a_no_op(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        stage_file(inbox / "a.txt", queue)
        assert stage_file(inbox / "a.txt", queue) is None
        assert len(list(queue.glob("*.json"))) == 1

    def test_item_carries_documents_and_warnings(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        item = stage_file(inbox / "a.txt", tmp_path / "queue")
        assert item["documents"][0]["text"] == "body"
        assert item["warnings"] == []


class TestScanInbox:
    def test_counts_staged_skipped_and_duplicates(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "one")
        (inbox / "b.md").write_text("# Two\n\ntwo")
        (inbox / "c.wav").write_bytes(b"\x00")
        queue = tmp_path / "queue"

        first = scan_inbox(inbox, queue)
        assert first["staged"] == 2
        assert first["skipped"] == 1

        second = scan_inbox(inbox, queue)
        assert second["staged"] == 0
        assert second["duplicates"] == 2

    def test_missing_inbox_is_not_an_error(self, tmp_path):
        result = scan_inbox(tmp_path / "nope", tmp_path / "queue")
        assert result == {"staged": 0, "skipped": 0, "duplicates": 0}


class TestLoadQueue:
    def test_returns_items_sorted_by_id(self, tmp_path):
        inbox = _inbox_with(tmp_path, "b.txt", "two")
        (inbox / "a.txt").write_text("one")
        queue = tmp_path / "queue"
        scan_inbox(inbox, queue)
        ids = [item["id"] for item in load_queue(queue)]
        assert ids == sorted(ids)

    def test_empty_queue_dir_returns_empty_list(self, tmp_path):
        assert load_queue(tmp_path / "queue") == []
