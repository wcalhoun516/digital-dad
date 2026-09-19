"""Tests for operator-console upload validation (plan 0011 step 2)."""

import pytest

from ingest.extract import HANDLERS
from ingest.upload import (
    MAX_UPLOAD_BYTES,
    UploadRejected,
    sanitize_filename,
    stage_upload,
    validate_upload,
)


class TestSanitizeFilename:
    def test_plain_name_passes_through(self):
        assert sanitize_filename("letter.txt") == "letter.txt"

    @pytest.mark.parametrize(
        "name",
        [
            "../etc/passwd",
            "..\\windows\\system32",
            "a/../../b.txt",
            "..",
            "....//x.txt",
        ],
    )
    def test_traversal_is_rejected(self, name):
        with pytest.raises(UploadRejected):
            sanitize_filename(name)

    @pytest.mark.parametrize(
        "name",
        ["dir/file.txt", "dir\\file.txt", "/absolute.txt", "C:\\abs.txt", "vol:file.txt"],
    )
    def test_path_separators_are_rejected(self, name):
        with pytest.raises(UploadRejected):
            sanitize_filename(name)

    @pytest.mark.parametrize("name", ["bad\x00.txt", "bad\n.txt", "bad\t.txt", "bad\x7f.txt"])
    def test_control_characters_are_rejected(self, name):
        with pytest.raises(UploadRejected):
            sanitize_filename(name)

    @pytest.mark.parametrize("name", ["", "   ", "."])
    def test_empty_or_dot_names_are_rejected(self, name):
        with pytest.raises(UploadRejected):
            sanitize_filename(name)

    def test_dotfile_is_rejected_because_the_inbox_scan_skips_it(self):
        # ingest.queue.scan_inbox ignores names starting with "." — accepting one here
        # would write a file that silently never gets staged.
        with pytest.raises(UploadRejected):
            sanitize_filename(".hidden.txt")

    def test_surrounding_whitespace_is_trimmed(self):
        assert sanitize_filename("  letter.txt  ") == "letter.txt"

    def test_overlong_name_is_rejected(self):
        with pytest.raises(UploadRejected):
            sanitize_filename("a" * 300 + ".txt")

    def test_rejection_message_names_the_offending_input(self):
        with pytest.raises(UploadRejected) as excinfo:
            sanitize_filename("../x.txt")
        assert "../x.txt" in str(excinfo.value)


class TestValidateUpload:
    def test_returns_the_safe_name(self):
        assert validate_upload("letter.txt", 10) == "letter.txt"

    def test_unsafe_name_is_still_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("../letter.txt", 10)

    def test_unregistered_extension_is_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("photo.jpeg", 10)

    def test_missing_extension_is_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("letter", 10)

    def test_extension_match_is_case_insensitive(self):
        assert validate_upload("LETTER.TXT", 10) == "LETTER.TXT"

    def test_allowlist_tracks_the_handler_registry(self):
        # The allowlist must be derived, not a second hand-maintained literal: registering
        # a new handler has to be the only edit needed to accept a new format.
        for ext in HANDLERS:
            assert validate_upload(f"doc{ext}", 10) == f"doc{ext}"

    def test_newly_registered_format_is_accepted_without_touching_upload(self, monkeypatch):
        monkeypatch.setitem(HANDLERS, ".zzz", lambda path: None)
        assert validate_upload("doc.zzz", 10) == "doc.zzz"

    def test_empty_file_is_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("letter.txt", 0)

    def test_file_at_the_cap_is_accepted(self):
        assert validate_upload("letter.txt", MAX_UPLOAD_BYTES) == "letter.txt"

    def test_file_over_the_cap_is_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("letter.txt", MAX_UPLOAD_BYTES + 1)

    def test_negative_size_is_rejected(self):
        with pytest.raises(UploadRejected):
            validate_upload("letter.txt", -1)


class TestStageUpload:
    def test_writes_the_bytes_into_the_inbox(self, tmp_path):
        path = stage_upload("letter.txt", b"a body", inbox=tmp_path / "inbox")
        assert path.read_bytes() == b"a body"
        assert path.parent == tmp_path / "inbox"

    def test_creates_a_missing_inbox(self, tmp_path):
        inbox = tmp_path / "nested" / "inbox"
        stage_upload("letter.txt", b"a body", inbox=inbox)
        assert inbox.is_dir()

    def test_rejects_a_traversal_name_without_writing_anything(self, tmp_path):
        inbox = tmp_path / "inbox"
        with pytest.raises(UploadRejected):
            stage_upload("../escaped.txt", b"a body", inbox=inbox)
        assert not (tmp_path / "escaped.txt").exists()
        assert list(inbox.glob("*")) == [] if inbox.exists() else True

    def test_rejects_an_unregistered_extension(self, tmp_path):
        with pytest.raises(UploadRejected):
            stage_upload("photo.jpeg", b"a body", inbox=tmp_path / "inbox")

    def test_size_is_measured_from_the_bytes_not_a_claimed_length(self, tmp_path):
        # The route hands over whatever the client sent; a Content-Length header is a claim,
        # the payload is the fact. The cap must apply to the fact.
        with pytest.raises(UploadRejected):
            stage_upload("letter.txt", b"x" * (MAX_UPLOAD_BYTES + 1), inbox=tmp_path / "inbox")

    def test_empty_payload_is_rejected(self, tmp_path):
        with pytest.raises(UploadRejected):
            stage_upload("letter.txt", b"", inbox=tmp_path / "inbox")

    def test_second_upload_of_the_same_name_does_not_clobber_the_first(self, tmp_path):
        inbox = tmp_path / "inbox"
        first = stage_upload("letter.txt", b"original", inbox=inbox)
        second = stage_upload("letter.txt", b"replacement", inbox=inbox)
        assert first != second
        assert first.read_bytes() == b"original"
        assert second.read_bytes() == b"replacement"

    def test_collision_suffix_keeps_the_extension_so_the_handler_still_matches(self, tmp_path):
        inbox = tmp_path / "inbox"
        stage_upload("letter.txt", b"original", inbox=inbox)
        second = stage_upload("letter.txt", b"replacement", inbox=inbox)
        assert second.suffix == ".txt"

    def test_many_collisions_each_get_their_own_file(self, tmp_path):
        inbox = tmp_path / "inbox"
        for i in range(5):
            stage_upload("letter.txt", f"body {i}".encode(), inbox=inbox)
        assert len(list(inbox.glob("*.txt"))) == 5

    def test_staged_file_is_picked_up_by_the_inbox_scan(self, tmp_path):
        # The whole point of writing here: ingest.queue.scan_inbox must find it.
        from ingest.queue import scan_inbox

        inbox = tmp_path / "inbox"
        stage_upload("letter.txt", b"a staged body", inbox=inbox)
        counts = scan_inbox(inbox, tmp_path / "queue")
        assert counts["staged"] == 1
