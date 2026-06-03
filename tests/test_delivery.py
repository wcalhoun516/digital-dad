"""Tests for analysis/delivery.py — On This Day recipient parsing + send dry-run.

These cover the approval-gated delivery path (plan 0003, approach 1): parsing the
gitignored recipient list and producing a dry-run summary that sends nothing. No
network, conductor, or Gmail MCP is exercised here.
"""

import json

from analysis.delivery import (
    format_dry_run,
    latest_email_payload,
    parse_recipients,
    read_recipients,
)


class TestParseRecipients:
    def test_one_address_per_line(self):
        assert parse_recipients("a@x.com\nb@y.com") == ["a@x.com", "b@y.com"]

    def test_ignores_blank_lines_and_comments(self):
        text = "# header comment\n\na@x.com\n  # indented comment\n\nb@y.com\n"
        assert parse_recipients(text) == ["a@x.com", "b@y.com"]

    def test_strips_surrounding_whitespace(self):
        assert parse_recipients("  a@x.com  \n\tb@y.com\t") == ["a@x.com", "b@y.com"]

    def test_dedupes_preserving_first_seen_order(self):
        text = "b@y.com\na@x.com\nb@y.com"
        assert parse_recipients(text) == ["b@y.com", "a@x.com"]

    def test_drops_entries_without_at_sign(self):
        text = "a@x.com\nnot-an-email\nb@y.com"
        assert parse_recipients(text) == ["a@x.com", "b@y.com"]

    def test_drops_entries_missing_local_or_domain(self):
        text = "@x.com\na@\na@x.com"
        assert parse_recipients(text) == ["a@x.com"]

    def test_empty_text_yields_empty_list(self):
        assert parse_recipients("") == []


class TestReadRecipients:
    def test_missing_file_returns_empty(self, tmp_path):
        assert read_recipients(tmp_path / "nope.txt") == []

    def test_reads_and_parses_file(self, tmp_path):
        p = tmp_path / "recipients.txt"
        p.write_text("# fam\nyou@example.com\nmom@example.com\n")
        assert read_recipients(p) == ["you@example.com", "mom@example.com"]


class TestLatestEmailPayload:
    def _setup(self, tmp_path, html="<html>hi</html>", meta=None):
        email_dir = tmp_path / "emails"
        email_dir.mkdir()
        (email_dir / "on_this_day_2026-06-01.html").write_text("<html>old</html>")
        (email_dir / "on_this_day_2026-06-03.html").write_text(html)
        log_path = tmp_path / "on_this_day.jsonl"
        if meta is not None:
            log_path.write_text(json.dumps(meta) + "\n")
        recipients_path = tmp_path / "recipients.txt"
        recipients_path.write_text("you@example.com\n")
        return email_dir, log_path, recipients_path

    def test_none_when_no_emails(self, tmp_path):
        email_dir = tmp_path / "emails"
        email_dir.mkdir()
        assert (
            latest_email_payload(email_dir, tmp_path / "log.jsonl", tmp_path / "r.txt")
            is None
        )

    def test_picks_latest_email_and_metadata(self, tmp_path):
        meta = {
            "subject": "From the archive — week of June 03, 2026",
            "headline": "Fed holds rates",
            "matched_article": "The Fed's Mistake",
        }
        email_dir, log_path, recipients_path = self._setup(
            tmp_path, html="<html>newest</html>", meta=meta
        )
        payload = latest_email_payload(email_dir, log_path, recipients_path)
        assert payload["to"] == ["you@example.com"]
        assert payload["subject"] == meta["subject"]
        assert payload["headline"] == "Fed holds rates"
        assert payload["matched_article"] == "The Fed's Mistake"
        assert payload["html_body"] == "<html>newest</html>"

    def test_falls_back_to_default_subject_without_meta(self, tmp_path):
        email_dir, log_path, recipients_path = self._setup(tmp_path, meta=None)
        payload = latest_email_payload(email_dir, log_path, recipients_path)
        assert payload["subject"] == "From the archive"


class TestFormatDryRun:
    def test_lists_recipients_and_sends_nothing_note(self):
        payload = {
            "to": ["you@example.com", "mom@example.com"],
            "subject": "From the archive",
            "headline": "Fed holds rates",
            "matched_article": "The Fed's Mistake",
            "html_body": "<html>" + "x" * 100 + "</html>",
        }
        out = format_dry_run(payload)
        assert "you@example.com" in out
        assert "mom@example.com" in out
        assert "From the archive" in out
        assert "2 recipient" in out
        assert "DRY RUN" in out.upper()

    def test_warns_when_no_recipients(self):
        payload = {
            "to": [],
            "subject": "From the archive",
            "headline": "",
            "matched_article": "",
            "html_body": "<html></html>",
        }
        out = format_dry_run(payload)
        assert "no recipients" in out.lower()
