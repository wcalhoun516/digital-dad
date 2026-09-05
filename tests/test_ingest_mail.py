"""Tests for the stdlib .eml/.mbox ingest handler (roadmap #32).

Every fixture is synthetic — no real family mail ever enters git.
"""

from ingest.extract import extract, handler_for


def write_eml(path, body, subject="A note on the Fed", sender="george@example.com", date=None):
    headers = [f"From: {sender}", "To: will@example.com", f"Subject: {subject}"]
    if date is not None:
        headers.append(f"Date: {date}")
    path.write_text("\n".join(headers) + "\n\n" + body, encoding="utf-8")
    return path


class TestRegistry:
    def test_eml_and_mbox_have_a_handler(self, tmp_path):
        assert handler_for(tmp_path / "a.eml") is not None
        assert handler_for(tmp_path / "a.mbox") is not None

    def test_extension_match_is_case_insensitive(self, tmp_path):
        assert handler_for(tmp_path / "A.EML") is not None


class TestSingleMessage:
    def test_one_message_yields_one_document(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "The Fed blinked. Again.\n")
        result = extract(path)
        assert len(result.documents) == 1
        assert "The Fed blinked." in result.documents[0]["text"]
        assert result.documents[0]["ordinal"] == 0

    def test_subject_becomes_the_document_and_source_title(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "body", subject="On Central Banking")
        result = extract(path)
        assert result.meta["title"] == "On Central Banking"
        assert result.documents[0]["title"] == "On Central Banking"

    def test_missing_subject_falls_back_to_the_filename_stem(self, tmp_path):
        path = tmp_path / "fed-note.eml"
        path.write_text("From: george@example.com\n\nbody\n")
        assert extract(path).meta["title"] == "fed-note"

    def test_date_header_becomes_an_exact_iso_date(self, tmp_path):
        path = write_eml(
            tmp_path / "note.eml", "body", date="Tue, 3 Mar 2020 09:15:00 -0500"
        )
        result = extract(path)
        assert result.meta["date"] == "2020-03-03"
        assert result.meta["date_confidence"] == "exact"

    def test_undated_message_warns_and_stays_unknown(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "body")
        result = extract(path)
        assert result.meta["date"] == ""
        assert result.meta["date_confidence"] == "unknown"
        assert any("date" in w.lower() for w in result.warnings)

    def test_unparseable_date_warns_rather_than_raising(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "body", date="last Thursday-ish")
        result = extract(path)
        assert result.meta["date"] == ""
        assert result.meta["date_confidence"] == "unknown"

    def test_modality_is_email(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "body")
        assert extract(path).meta["modality"] == "email"

    def test_clean_message_is_high_confidence_with_no_warnings(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "body", date="Tue, 3 Mar 2020 09:15:00 -0500")
        result = extract(path)
        assert result.confidence == 1.0
        assert result.warnings == []

    def test_empty_body_warns_and_drops_confidence(self, tmp_path):
        path = write_eml(tmp_path / "note.eml", "   \n", date="Tue, 3 Mar 2020 09:15:00 -0500")
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0
        assert any("empty" in w.lower() for w in result.warnings)


class TestMultipart:
    def test_text_plain_part_wins_over_html(self, tmp_path):
        path = tmp_path / "note.eml"
        path.write_text(
            "From: george@example.com\n"
            "Subject: Multipart\n"
            'Content-Type: multipart/alternative; boundary="B"\n'
            "\n"
            "--B\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            "The plain text body.\n"
            "--B\n"
            "Content-Type: text/html; charset=utf-8\n"
            "\n"
            "<p>The HTML body.</p>\n"
            "--B--\n"
        )
        result = extract(path)
        assert "The plain text body." in result.documents[0]["text"]
        assert "HTML" not in result.documents[0]["text"]

    def test_declared_charset_is_decoded(self, tmp_path):
        path = tmp_path / "note.eml"
        path.write_bytes(
            b"From: george@example.com\n"
            b"Subject: Charset\n"
            b"Content-Type: text/plain; charset=iso-8859-1\n"
            b"\n"
            b"Se\xf1or Draghi\n"
        )
        assert "Señor Draghi" in extract(path).documents[0]["text"]

    def test_attachment_only_message_warns_about_no_text(self, tmp_path):
        path = tmp_path / "scan.eml"
        path.write_text(
            "From: george@example.com\n"
            "Subject: Scan\n"
            'Content-Type: multipart/mixed; boundary="B"\n'
            "\n"
            "--B\n"
            "Content-Type: application/pdf\n"
            'Content-Disposition: attachment; filename="scan.pdf"\n'
            "\n"
            "%PDF-1.4\n"
            "--B--\n"
        )
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0
        assert any("text" in w.lower() for w in result.warnings)


class TestQuotedReplyStripping:
    def test_quoted_lines_are_removed(self, tmp_path):
        path = write_eml(
            tmp_path / "reply.eml",
            "My own view is that the ECB is out of room.\n"
            "\n"
            "> What did you make of the ECB decision?\n"
            "> - Will\n",
        )
        text = extract(path).documents[0]["text"]
        assert "ECB is out of room" in text
        assert "What did you make" not in text

    def test_attribution_line_and_everything_after_is_removed(self, tmp_path):
        path = write_eml(
            tmp_path / "reply.eml",
            "Short answer: no.\n"
            "\n"
            "On Tue, Mar 3, 2020 at 9:15 AM Will <will@example.com> wrote:\n"
            "Did the Fed have a choice?\n",
        )
        text = extract(path).documents[0]["text"]
        assert "Short answer: no." in text
        assert "Did the Fed have a choice?" not in text
        assert "wrote:" not in text

    def test_signature_block_is_removed(self, tmp_path):
        path = write_eml(
            tmp_path / "note.eml",
            "The point stands.\n\n-- \nGeorge Calhoun\nStevens Institute\n",
        )
        text = extract(path).documents[0]["text"]
        assert "The point stands." in text
        assert "Stevens Institute" not in text

    def test_a_reply_with_nothing_but_quotes_is_treated_as_empty(self, tmp_path):
        path = write_eml(tmp_path / "reply.eml", "> only quoted material\n> nothing of his\n")
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0


class TestMbox:
    def test_mbox_yields_one_document_per_message_in_order(self, tmp_path):
        path = tmp_path / "thread.mbox"
        path.write_text(
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: First\n"
            "\n"
            "The first message.\n"
            "\n"
            "From george@example.com Wed Mar 04 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: Second\n"
            "\n"
            "The second message.\n"
        )
        result = extract(path)
        assert len(result.documents) == 2
        assert [doc["ordinal"] for doc in result.documents] == [0, 1]
        assert result.documents[0]["title"] == "First"
        assert "The second message." in result.documents[1]["text"]

    def test_source_title_is_the_filename_stem_for_an_mbox(self, tmp_path):
        path = tmp_path / "fed-thread.mbox"
        path.write_text(
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: First\n"
            "\n"
            "Body.\n"
        )
        assert extract(path).meta["title"] == "fed-thread"

    def test_source_date_is_the_earliest_message_date(self, tmp_path):
        path = tmp_path / "thread.mbox"
        path.write_text(
            "From george@example.com Wed Mar 04 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: Later\n"
            "Date: Wed, 4 Mar 2020 09:15:00 -0500\n"
            "\n"
            "Later body.\n"
            "\n"
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: Earlier\n"
            "Date: Tue, 3 Mar 2020 09:15:00 -0500\n"
            "\n"
            "Earlier body.\n"
        )
        result = extract(path)
        assert result.meta["date"] == "2020-03-03"
        assert result.meta["date_confidence"] == "exact"

    def test_a_single_sender_thread_stays_authored_by_george(self, tmp_path):
        path = tmp_path / "thread.mbox"
        path.write_text(
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: First\n"
            "\n"
            "Body.\n"
        )
        assert extract(path).meta["authorship"] == "george"

    def test_multiple_senders_make_the_thread_mixed(self, tmp_path):
        path = tmp_path / "thread.mbox"
        path.write_text(
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: First\n"
            "\n"
            "His message.\n"
            "\n"
            "From will@example.com Wed Mar 04 09:15:00 2020\n"
            "From: will@example.com\n"
            "Subject: Re: First\n"
            "\n"
            "My reply.\n"
        )
        assert extract(path).meta["authorship"] == "mixed"

    def test_empty_messages_are_dropped_but_the_rest_survive(self, tmp_path):
        path = tmp_path / "thread.mbox"
        path.write_text(
            "From george@example.com Tue Mar 03 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: Empty\n"
            "\n"
            "> only a quote\n"
            "\n"
            "From george@example.com Wed Mar 04 09:15:00 2020\n"
            "From: george@example.com\n"
            "Subject: Real\n"
            "\n"
            "Real content here.\n"
        )
        result = extract(path)
        assert len(result.documents) == 1
        assert result.documents[0]["title"] == "Real"
        assert result.documents[0]["ordinal"] == 0
        assert any("empty" in w.lower() or "dropped" in w.lower() for w in result.warnings)

    def test_an_empty_mbox_warns_at_zero_confidence(self, tmp_path):
        path = tmp_path / "empty.mbox"
        path.write_text("")
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0
        assert result.warnings
