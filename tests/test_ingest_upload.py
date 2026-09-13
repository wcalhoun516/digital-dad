"""Tests for operator-console upload validation (plan 0011 step 2)."""

import pytest

from ingest.extract import HANDLERS
from ingest.upload import (
    MAX_UPLOAD_BYTES,
    UploadRejected,
    sanitize_filename,
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
