"""Tests for scraper/manifest_check.py — the manifest integrity checker (roadmap #8)."""

import json

from scraper.manifest_check import (
    audit_manifest,
    format_report,
    run,
    scan_raw_files,
)


def _entry(slug, *, url=None, file=None, content_hash="h-" + "x", **extra):
    """Build a manifest entry, defaulting url/file/content_hash off the slug."""
    e = {
        "slug": slug,
        "url": url if url is not None else f"https://forbes.com/{slug}/",
        "file": file if file is not None else f"raw/{slug}.json",
        "content_hash": content_hash,
    }
    e.update(extra)
    return e


def _manifest(entries, *, total=None):
    return {
        "total_articles": len(entries) if total is None else total,
        "articles": entries,
    }


def _disk(entries):
    """The set of raw files a clean manifest would have on disk."""
    return {e["file"] for e in entries}


class TestClean:
    def test_clean_manifest_reports_ok(self):
        entries = [
            _entry("alpha", content_hash="h1"),
            _entry("beta", content_hash="h2"),
        ]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["ok"] is True
        assert report["issue_count"] == 0
        assert report["article_count"] == 2

    def test_clean_collections_are_empty(self):
        entries = [_entry("alpha", content_hash="h1"), _entry("beta", content_hash="h2")]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["duplicate_slugs"] == {}
        assert report["duplicate_urls"] == {}
        assert report["duplicate_content_hashes"] == {}
        assert report["missing_content_hash"] == []
        assert report["missing_files"] == []
        assert report["orphaned_files"] == []
        assert report["entries_missing_file_field"] == []
        assert report["count_drift"] is False


class TestDuplicates:
    def test_duplicate_slug_detected(self):
        # Same slug from two different URLs (the real-world tier-rediscovery dup).
        entries = [
            _entry("dup", url="https://forbes.com/a/", content_hash="h1"),
            _entry("dup", url="https://forbes.com/b/", content_hash="h1"),
        ]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["duplicate_slugs"] == {"dup": 2}
        assert report["ok"] is False

    def test_duplicate_url_detected(self):
        entries = [
            _entry("a", url="https://forbes.com/same/", content_hash="h1"),
            _entry("b", url="https://forbes.com/same/", content_hash="h2"),
        ]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["duplicate_urls"] == {"https://forbes.com/same/": 2}

    def test_duplicate_content_hash_maps_to_slugs(self):
        entries = [
            _entry("a", content_hash="same"),
            _entry("b", content_hash="same"),
            _entry("c", content_hash="unique"),
        ]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["duplicate_content_hashes"] == {"same": ["a", "b"]}

    def test_empty_content_hash_not_treated_as_duplicate(self):
        entries = [_entry("a", content_hash=""), _entry("b", content_hash="")]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["duplicate_content_hashes"] == {}


class TestMissingContentHash:
    def test_missing_field_listed(self):
        a = _entry("a", content_hash="h1")
        b = {"slug": "b", "url": "https://forbes.com/b/", "file": "raw/b.json"}  # no hash
        entries = [a, b]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["missing_content_hash"] == ["b"]

    def test_empty_hash_counts_as_missing(self):
        entries = [_entry("a", content_hash=""), _entry("b", content_hash="h2")]
        report = audit_manifest(_manifest(entries), _disk(entries))
        assert report["missing_content_hash"] == ["a"]


class TestDiskDrift:
    def test_missing_file_referenced_but_absent(self):
        entries = [_entry("a", content_hash="h1"), _entry("ghost", content_hash="h2")]
        on_disk = {"raw/a.json"}  # ghost.json absent
        report = audit_manifest(_manifest(entries), on_disk)
        assert report["missing_files"] == ["raw/ghost.json"]

    def test_orphaned_file_on_disk_unreferenced(self):
        entries = [_entry("a", content_hash="h1")]
        on_disk = {"raw/a.json", "raw/orphan.json"}
        report = audit_manifest(_manifest(entries), on_disk)
        assert report["orphaned_files"] == ["raw/orphan.json"]

    def test_entry_missing_file_field(self):
        a = {"slug": "a", "url": "https://forbes.com/a/", "content_hash": "h1"}  # no file
        report = audit_manifest(_manifest([a]), set())
        assert report["entries_missing_file_field"] == ["a"]
        assert report["missing_files"] == []  # a missing field is not a missing-on-disk file


class TestCountDrift:
    def test_declared_total_mismatch_flagged(self):
        entries = [_entry("a", content_hash="h1"), _entry("b", content_hash="h2")]
        report = audit_manifest(_manifest(entries, total=99), _disk(entries))
        assert report["count_drift"] is True
        assert report["declared_total"] == 99
        assert report["article_count"] == 2

    def test_issue_count_aggregates_all_findings(self):
        entries = [
            _entry("dup", url="https://forbes.com/a/", content_hash="same"),
            _entry("dup", url="https://forbes.com/b/", content_hash="same"),
        ]
        # duplicate_slugs(1) + duplicate_content_hashes(1) + count_drift(1) = 3
        report = audit_manifest(_manifest(entries, total=5), _disk(entries))
        assert report["issue_count"] == 3


class TestFormatReport:
    def test_clean_report_says_ok(self):
        entries = [_entry("a", content_hash="h1")]
        text = format_report(audit_manifest(_manifest(entries), _disk(entries)))
        assert "OK" in text or "no issues" in text.lower()

    def test_dirty_report_mentions_duplicate_slugs(self):
        entries = [
            _entry("dup", url="https://forbes.com/a/", content_hash="h1"),
            _entry("dup", url="https://forbes.com/b/", content_hash="h1"),
        ]
        text = format_report(audit_manifest(_manifest(entries), _disk(entries)))
        assert "dup" in text
        assert "slug" in text.lower()


class TestScanRawFiles:
    def test_returns_relative_raw_paths(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "a.json").write_text("{}")
        (raw / "b.json").write_text("{}")
        (raw / "notes.txt").write_text("ignore me")  # non-json ignored
        assert scan_raw_files(raw) == {"raw/a.json", "raw/b.json"}

    def test_missing_dir_returns_empty(self, tmp_path):
        assert scan_raw_files(tmp_path / "does-not-exist") == set()


def _write_corpus(tmp_path, entries, *, total=None, on_disk=None):
    """Write a manifest.json + raw/*.json under tmp_path; return (manifest_path, raw_dir)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    files = on_disk if on_disk is not None else [e["file"] for e in entries]
    for f in files:
        (tmp_path / f).write_text("{}")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(entries, total=total)))
    return manifest_path, raw


class TestRun:
    def test_clean_returns_zero(self, tmp_path, capsys):
        entries = [_entry("a", content_hash="h1")]
        mp, raw = _write_corpus(tmp_path, entries)
        assert run(mp, raw) == 0
        assert "OK" in capsys.readouterr().out

    def test_non_strict_returns_zero_even_with_issues(self, tmp_path, capsys):
        entries = [_entry("a", content_hash="h1")]
        mp, raw = _write_corpus(tmp_path, entries, total=42)  # count drift
        assert run(mp, raw, strict=False) == 0

    def test_strict_returns_one_on_issues(self, tmp_path, capsys):
        entries = [_entry("a", content_hash="h1")]
        mp, raw = _write_corpus(tmp_path, entries, total=42)  # count drift
        assert run(mp, raw, strict=True) == 1

    def test_missing_manifest_returns_one(self, tmp_path, capsys):
        assert run(tmp_path / "absent.json", tmp_path / "raw") == 1

    def test_json_output_is_valid_and_machine_readable(self, tmp_path, capsys):
        entries = [
            _entry("dup", url="https://forbes.com/a/", content_hash="h1"),
            _entry("dup", url="https://forbes.com/b/", content_hash="h1"),
        ]
        mp, raw = _write_corpus(tmp_path, entries)
        run(mp, raw, as_json=True)
        data = json.loads(capsys.readouterr().out)
        assert data["duplicate_slugs"] == {"dup": 2}
        assert data["ok"] is False
