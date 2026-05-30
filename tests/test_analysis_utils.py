"""Characterization tests for analysis/utils.py pure helpers."""

from analysis.utils import chunk_text, clean_text


class TestCleanText:
    def test_removes_twitter_boilerplate_keeps_body(self):
        text = "The economy is strong. Follow me on Twitter @gcalhoun"
        assert clean_text(text) == "The economy is strong."

    def test_removes_opinions_disclaimer(self):
        text = "Inflation will rise. The opinions expressed here are my own."
        assert clean_text(text) == "Inflation will rise."

    def test_is_case_insensitive(self):
        text = "Markets fell. follow me on twitter for more"
        assert clean_text(text) == "Markets fell."

    def test_normalizes_whitespace(self):
        assert clean_text("foo\n\n   bar\t baz") == "foo bar baz"


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        assert chunk_text("short body") == ["short body"]

    def test_long_text_splits_into_multiple_chunks(self):
        text = "First part ends here. Second part is long enough here too."
        chunks = chunk_text(text, max_tokens=10, overlap=2)
        assert len(chunks) > 1

    def test_splits_on_sentence_boundary(self):
        text = "First part ends here. Second part is long enough here too."
        chunks = chunk_text(text, max_tokens=10, overlap=2)
        assert chunks[0] == "First part ends here."

    def test_respects_max_chars_and_drops_nothing(self):
        text = "First part ends here. Second part is long enough here too."
        chunks = chunk_text(text, max_tokens=10, overlap=2)
        # max_chars = max_tokens * 4 = 40
        assert all(len(c) <= 40 for c in chunks)
        assert all(c for c in chunks)
        # the tail of the source survives in the final chunk
        assert chunks[-1].endswith("too.")
