"""Tests for operator-console upload validation (plan 0011 step 2)."""

import pytest

from ingest.upload import UploadRejected, sanitize_filename


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
