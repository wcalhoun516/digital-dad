"""Tests for the ingest handler registry and the stdlib plaintext handler (roadmap #30)."""

import pytest

from ingest.extract import ExtractResult, UnsupportedFormat, extract, handler_for


class TestRegistry:
    def test_txt_and_md_have_a_handler(self, tmp_path):
        assert handler_for(tmp_path / "a.txt") is not None
        assert handler_for(tmp_path / "a.md") is not None

    def test_extension_match_is_case_insensitive(self, tmp_path):
        assert handler_for(tmp_path / "A.TXT") is not None

    def test_unknown_extension_has_no_handler(self, tmp_path):
        assert handler_for(tmp_path / "a.wav") is None

    def test_extract_raises_on_unsupported_format(self, tmp_path):
        path = tmp_path / "a.wav"
        path.write_bytes(b"\x00")
        with pytest.raises(UnsupportedFormat, match=".wav"):
            extract(path)


class TestPlaintextHandler:
    def test_returns_one_document_with_the_file_text(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("The Fed blinked.\nAgain.\n")
        result = extract(path)
        assert isinstance(result, ExtractResult)
        assert len(result.documents) == 1
        assert "The Fed blinked." in result.documents[0]["text"]
        assert result.documents[0]["ordinal"] == 0

    def test_title_falls_back_to_the_filename_stem(self, tmp_path):
        path = tmp_path / "fed-note.txt"
        path.write_text("body")
        assert extract(path).meta["title"] == "fed-note"

    def test_markdown_h1_becomes_the_title(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("# On Central Banking\n\nBody text.\n")
        assert extract(path).meta["title"] == "On Central Banking"

    def test_plaintext_is_high_confidence_with_no_warnings(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("body")
        result = extract(path)
        assert result.confidence == 1.0
        assert result.warnings == []

    def test_empty_file_warns_and_drops_confidence(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("   \n")
        result = extract(path)
        assert result.confidence == 0.0
        assert any("empty" in w.lower() for w in result.warnings)

    def test_meta_carries_no_date_for_plaintext(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("body")
        result = extract(path)
        assert result.meta["date"] == ""
        assert result.meta["date_confidence"] == "unknown"
