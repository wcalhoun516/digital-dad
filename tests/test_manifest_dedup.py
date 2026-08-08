"""Tests for scraper/manifest_dedup.py — the manifest de-dup / repair tool (roadmap #8
follow-up: the fix manifest_check only reports)."""

import json

from scraper.manifest_dedup import (
    backfill_hashes,
    content_hash_for,
    dedup_articles,
    format_dedup_report,
    run,
)


def _entry(slug, *, url=None, content_hash="h", **extra):
    e = {
        "slug": slug,
        "url": url if url is not None else f"https://www.forbes.com/{slug}/",
        "file": f"raw/{slug}.json",
        "content_hash": content_hash,
    }
    e.update(extra)
    return e


def _manifest(entries):
    return {"total_articles": len(entries), "articles": entries}


class TestDedupArticles:
    def test_clean_manifest_is_unchanged_with_no_actions(self):
        entries = [_entry("alpha"), _entry("beta")]
        deduped, actions = dedup_articles(entries)
        assert [e["slug"] for e in deduped] == ["alpha", "beta"]
        assert actions == []

    def test_collapses_two_entries_sharing_a_slug(self):
        entries = [
            _entry("dupe", url="https://www.forbes.com/dupe/"),
            _entry("dupe", url="https://www.forbes.com/dupe/?sh=abc"),
        ]
        deduped, actions = dedup_articles(entries)
        assert len(deduped) == 1
        assert deduped[0]["slug"] == "dupe"

    def test_prefers_entry_that_has_a_content_hash(self):
        entries = [
            _entry("dupe", url="https://a/", content_hash=""),
            _entry("dupe", url="https://b/", content_hash="real"),
        ]
        deduped, _ = dedup_articles(entries)
        assert deduped[0]["url"] == "https://b/"
        assert deduped[0]["content_hash"] == "real"

    def test_prefers_url_without_a_query_string(self):
        entries = [
            _entry("dupe", url="https://www.forbes.com/dupe/?sh=abc"),
            _entry("dupe", url="https://www.forbes.com/dupe/"),
        ]
        deduped, _ = dedup_articles(entries)
        assert deduped[0]["url"] == "https://www.forbes.com/dupe/"

    def test_prefers_https_over_http_when_otherwise_equal(self):
        entries = [
            _entry("dupe", url="http://forbes.com/dupe/"),
            _entry("dupe", url="https://forbes.com/dupe/"),
        ]
        deduped, _ = dedup_articles(entries)
        assert deduped[0]["url"] == "https://forbes.com/dupe/"

    def test_kept_entries_preserve_first_seen_order(self):
        entries = [
            _entry("alpha"),
            _entry("dupe", url="https://www.forbes.com/dupe/?sh=x"),
            _entry("beta"),
            _entry("dupe", url="https://www.forbes.com/dupe/"),
        ]
        deduped, _ = dedup_articles(entries)
        assert [e["slug"] for e in deduped] == ["alpha", "dupe", "beta"]

    def test_actions_record_kept_and_dropped_urls(self):
        entries = [
            _entry("dupe", url="https://www.forbes.com/dupe/"),
            _entry("dupe", url="https://www.forbes.com/dupe/?sh=abc"),
        ]
        _, actions = dedup_articles(entries)
        assert len(actions) == 1
        assert actions[0]["slug"] == "dupe"
        assert actions[0]["kept_url"] == "https://www.forbes.com/dupe/"
        assert actions[0]["dropped_urls"] == ["https://www.forbes.com/dupe/?sh=abc"]

    def test_collapses_three_entries_to_one(self):
        entries = [
            _entry("dupe", url="https://a/?q=1"),
            _entry("dupe", url="https://b/"),
            _entry("dupe", url="https://c/?q=2"),
        ]
        deduped, actions = dedup_articles(entries)
        assert len(deduped) == 1
        assert deduped[0]["url"] == "https://b/"
        assert sorted(actions[0]["dropped_urls"]) == ["https://a/?q=1", "https://c/?q=2"]

    def test_missing_slug_entries_are_left_untouched(self):
        entries = [_entry("", url="https://x/"), _entry("", url="https://y/")]
        deduped, actions = dedup_articles(entries)
        assert len(deduped) == 2
        assert actions == []

    def test_does_not_mutate_input(self):
        entries = [_entry("dupe", url="https://a/"), _entry("dupe", url="https://b/?q")]
        dedup_articles(entries)
        assert len(entries) == 2


class TestContentHashFor:
    def test_matches_the_scrapers_md5_of_the_body(self):
        import hashlib

        body = "Some article body text."
        expected = hashlib.md5(body.encode()).hexdigest()
        assert content_hash_for(body) == expected

    def test_none_body_hashes_like_empty_string(self):
        import hashlib

        assert content_hash_for(None) == hashlib.md5(b"").hexdigest()


class TestBackfillHashes:
    def test_fills_missing_hash_from_raw_body(self):
        entries = [_entry("alpha", content_hash="")]
        bodies = {"raw/alpha.json": "hello world"}
        filled, count = backfill_hashes(entries, bodies.get)
        assert count == 1
        assert filled[0]["content_hash"] == content_hash_for("hello world")

    def test_leaves_existing_hashes_alone(self):
        entries = [_entry("alpha", content_hash="already")]
        filled, count = backfill_hashes(entries, lambda f: "ignored")
        assert count == 0
        assert filled[0]["content_hash"] == "already"

    def test_skips_entry_when_body_unavailable(self):
        entries = [_entry("alpha", content_hash="")]
        filled, count = backfill_hashes(entries, lambda f: None)
        assert count == 0
        assert filled[0]["content_hash"] == ""


class TestFormatReport:
    def test_reports_no_changes_for_a_clean_manifest(self):
        entries = [_entry("alpha"), _entry("beta")]
        text = format_dedup_report(entries, entries, [])
        assert "no duplicate slugs" in text.lower()

    def test_reports_collapsed_counts(self):
        original = [_entry("dupe", url="https://a/"), _entry("dupe", url="https://b/?q")]
        deduped, actions = dedup_articles(original)
        text = format_dedup_report(original, deduped, actions)
        assert "2" in text and "1" in text
        assert "dupe" in text


class TestRunCLI:
    def _write_manifest(self, tmp_path, entries):
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(_manifest(entries)))
        return p

    def test_report_mode_does_not_modify_the_manifest(self, tmp_path, capsys):
        entries = [_entry("dupe", url="https://a/"), _entry("dupe", url="https://b/?q")]
        mpath = self._write_manifest(tmp_path, entries)
        before = mpath.read_text()
        rc = run(manifest_path=mpath)
        assert rc == 0
        assert mpath.read_text() == before  # untouched

    def test_apply_writes_deduped_manifest_to_a_separate_file(self, tmp_path):
        entries = [_entry("dupe", url="https://a/"), _entry("dupe", url="https://b/?q")]
        mpath = self._write_manifest(tmp_path, entries)
        out = tmp_path / "manifest.dedup.json"
        rc = run(manifest_path=mpath, apply=True, output=out)
        assert rc == 0
        written = json.loads(out.read_text())
        assert len(written["articles"]) == 1
        assert written["total_articles"] == 1
        assert mpath.read_text() == json.dumps(_manifest(entries))  # original untouched

    def test_in_place_rewrites_the_manifest_and_refreshes_total(self, tmp_path):
        entries = [_entry("dupe", url="https://a/"), _entry("dupe", url="https://b/?q")]
        mpath = self._write_manifest(tmp_path, entries)
        rc = run(manifest_path=mpath, apply=True, in_place=True)
        assert rc == 0
        written = json.loads(mpath.read_text())
        assert len(written["articles"]) == 1
        assert written["total_articles"] == 1

    def test_missing_manifest_returns_one(self, tmp_path):
        rc = run(manifest_path=tmp_path / "nope.json")
        assert rc == 1
