"""Characterization tests for analysis/utils.py pure helpers."""

import json

from analysis import utils
from analysis.utils import chunk_text, clean_text, dedupe_manifest_entries


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


class TestDedupeManifestEntries:
    """One raw file is one article. The real manifest holds 199 entries for 176
    distinct files (23 http/https twins), so the corpus walker must not read the
    same article twice — see PR #18 (found), PR #76 (proved it corrupts output)."""

    def test_distinct_files_are_all_kept(self):
        entries = [{"file": "raw/a.json"}, {"file": "raw/b.json"}]
        assert dedupe_manifest_entries(entries) == entries

    def test_two_entries_naming_the_same_file_collapse_to_one(self):
        entries = [
            {"slug": "dup", "url": "http://forbes.com/dup/", "file": "raw/dup.json"},
            {"slug": "dup", "url": "https://forbes.com/dup/", "file": "raw/dup.json"},
        ]
        assert len(dedupe_manifest_entries(entries)) == 1

    def test_first_occurrence_is_the_one_kept(self):
        entries = [
            {"slug": "dup", "url": "first", "file": "raw/dup.json"},
            {"slug": "dup", "url": "second", "file": "raw/dup.json"},
        ]
        assert dedupe_manifest_entries(entries)[0]["url"] == "first"

    def test_order_is_preserved(self):
        entries = [
            {"file": "raw/a.json"},
            {"file": "raw/dup.json"},
            {"file": "raw/b.json"},
            {"file": "raw/dup.json"},
        ]
        kept = [e["file"] for e in dedupe_manifest_entries(entries)]
        assert kept == ["raw/a.json", "raw/dup.json", "raw/b.json"]

    def test_different_slugs_sharing_a_file_still_collapse(self):
        # Same file means the same document text — loading it twice double-counts it
        # regardless of what the entries call themselves.
        entries = [
            {"slug": "a", "file": "raw/same.json"},
            {"slug": "b", "file": "raw/same.json"},
        ]
        assert len(dedupe_manifest_entries(entries)) == 1

    def test_entries_without_a_file_field_are_not_merged_together(self):
        entries = [{"slug": "a"}, {"slug": "b"}]
        assert len(dedupe_manifest_entries(entries)) == 2

    def test_empty_list_is_handled(self):
        assert dedupe_manifest_entries([]) == []


def _write_corpus(tmp_path, entries, bodies):
    """Write a manifest + raw/*.json under tmp_path so load_articles can read it."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, article in bodies.items():
        (raw / name).write_text(json.dumps(article))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"total_articles": len(entries), "articles": entries})
    )


class TestLoadArticles:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "DATA_DIR", tmp_path)
        monkeypatch.setattr(utils, "MANIFEST_PATH", tmp_path / "manifest.json")

    def test_a_duplicated_manifest_entry_yields_one_article(self, tmp_path, monkeypatch):
        entries = [
            {"slug": "dup", "url": "http://forbes.com/dup/", "file": "raw/dup.json"},
            {"slug": "dup", "url": "https://forbes.com/dup/", "file": "raw/dup.json"},
        ]
        _write_corpus(tmp_path, entries, {"dup.json": {"date": "2021-01-01", "body": "x"}})
        self._patch(monkeypatch, tmp_path)
        assert len(utils.load_articles()) == 1

    def test_distinct_articles_are_all_loaded(self, tmp_path, monkeypatch):
        entries = [{"file": "raw/a.json"}, {"file": "raw/b.json"}]
        _write_corpus(
            tmp_path,
            entries,
            {"a.json": {"date": "2021-01-01"}, "b.json": {"date": "2021-02-01"}},
        )
        self._patch(monkeypatch, tmp_path)
        assert len(utils.load_articles()) == 2

    def test_articles_stay_sorted_by_date(self, tmp_path, monkeypatch):
        entries = [{"file": "raw/late.json"}, {"file": "raw/early.json"}]
        _write_corpus(
            tmp_path,
            entries,
            {"late.json": {"date": "2022-01-01"}, "early.json": {"date": "2020-01-01"}},
        )
        self._patch(monkeypatch, tmp_path)
        dates = [a["date"] for a in utils.load_articles()]
        assert dates == ["2020-01-01", "2022-01-01"]

    def test_entry_whose_file_is_absent_is_skipped(self, tmp_path, monkeypatch):
        entries = [{"file": "raw/there.json"}, {"file": "raw/gone.json"}]
        _write_corpus(tmp_path, entries, {"there.json": {"date": "2021-01-01"}})
        self._patch(monkeypatch, tmp_path)
        assert len(utils.load_articles()) == 1
