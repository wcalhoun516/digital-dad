"""Tests for the ``.pdf`` ingest handler (roadmap #34).

Every fixture here is a **synthetic** PDF written byte-by-byte into ``tmp_path``: no real
document and no family content ever enters git (ingest design testing rule, D7). The
writer is deliberately tiny — one Helvetica font, one text object per page — because the
handler's job is the *reading*, and a hand-built file pins exactly what a page contains.
"""

import io
import sys

import pytest


def _pdf_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages, info=None) -> bytes:
    """A minimal valid PDF. ``pages`` is a list of line lists; an empty list is a page with
    no text layer at all — the shape a scanned page takes. ``""`` inside a page is a blank
    line, which is how a paragraph break is drawn."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    tree = add(b"")  # the page tree, filled in once the kids exist
    kids = []
    for lines in pages:
        ops = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
        ops += [f"({_pdf_string(line)}) Tj T*" for line in lines]
        stream = "\n".join(ops + ["ET"]).encode("latin-1") if lines else b""
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(
            add(
                f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode()
            )
        )
    refs = " ".join(f"{kid} 0 R" for kid in kids)
    objects[tree - 1] = f"<< /Type /Pages /Kids [{refs}] /Count {len(kids)} >>".encode()
    catalog = add(f"<< /Type /Catalog /Pages {tree} 0 R >>".encode())
    info_ref = ""
    if info:
        fields = " ".join(f"/{key} ({_pdf_string(value)})" for key, value in info.items())
        info_ref = f" /Info {add(f'<< {fields} >>'.encode('latin-1'))} 0 R"

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R{info_ref} >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


HIS = {"Title": "Notes on Money", "Author": "George Calhoun", "CreationDate": "D:20190312093000"}


def write_pdf(path, pages, info=HIS):
    path.write_bytes(build_pdf(pages, info))
    return path


def encrypted(pdf_bytes: bytes, user_password: str) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestRegistration:
    def test_pdf_is_a_registered_extension(self):
        from ingest.extract import handler_for
        from ingest.handlers.pdf import extract_pdf

        assert handler_for("lecture.PDF") is extract_pdf


class TestTextLayer:
    def test_a_text_pdf_becomes_one_document_with_his_words(self, tmp_path):
        from ingest.extract import extract

        path = write_pdf(tmp_path / "notes.pdf", [["The Fed is late to every cycle."]])
        result = extract(path)
        assert len(result.documents) == 1
        assert "The Fed is late to every cycle." in result.documents[0]["text"]
        assert result.documents[0]["ordinal"] == 0
        assert result.confidence == 1.0

    def test_wrapped_lines_rejoin_and_blank_lines_keep_paragraphs(self, tmp_path):
        from ingest.extract import extract

        # Paragraph structure is what plan 0009's passage-level training records are cut
        # on; a PDF hard-wraps every line, so both halves of this matter.
        path = write_pdf(
            tmp_path / "notes.pdf",
            [["Rates rose in the", "spring of that year.", "", "Then they fell."]],
        )
        text = extract(path).documents[0]["text"]
        assert text == "Rates rose in the spring of that year.\n\nThen they fell."

    def test_pages_are_read_in_order_and_each_ends_a_paragraph(self, tmp_path):
        from ingest.extract import extract

        path = write_pdf(tmp_path / "notes.pdf", [["First page."], ["Second page."]])
        assert extract(path).documents[0]["text"] == "First page.\n\nSecond page."

    def test_bare_page_numbers_at_the_top_or_bottom_of_a_page_are_dropped(self, tmp_path):
        from ingest.extract import extract

        path = write_pdf(
            tmp_path / "notes.pdf",
            [["An argument about banks.", "", "12"], ["13", "", "A further argument."]],
        )
        text = extract(path).documents[0]["text"]
        assert "12" not in text and "13" not in text
        assert text == "An argument about banks.\n\nA further argument."

    def test_a_number_inside_the_prose_is_kept(self, tmp_path):
        from ingest.extract import extract

        path = write_pdf(tmp_path / "notes.pdf", [["Consider the year", "", "1987", "", "End."]])
        assert "1987" in extract(path).documents[0]["text"]


class TestMetadata:
    def test_title_author_and_date_come_from_the_document_info(self, tmp_path):
        from ingest.extract import extract

        result = extract(write_pdf(tmp_path / "file.pdf", [["Text."]]))
        assert result.meta["title"] == "Notes on Money"
        assert result.documents[0]["title"] == "Notes on Money"
        assert result.meta["authorship"] == "george"
        # A PDF's creation date is when the *file* was made, not when he wrote it.
        assert (result.meta["date"], result.meta["date_confidence"]) == (
            "2019-03-12",
            "approximate",
        )

    def test_a_missing_title_falls_back_to_the_filename_with_a_warning(self, tmp_path):
        from ingest.extract import extract

        info = {"Author": "George Calhoun"}
        result = extract(write_pdf(tmp_path / "syllabus-2014.pdf", [["Text."]], info))
        assert result.meta["title"] == "syllabus-2014"
        assert any("title" in warning for warning in result.warnings)

    def test_no_date_is_unknown_not_invented(self, tmp_path):
        from ingest.extract import extract

        info = {"Title": "T", "Author": "George Calhoun"}
        result = extract(write_pdf(tmp_path / "f.pdf", [["Text."]], info))
        assert (result.meta["date"], result.meta["date_confidence"]) == ("", "unknown")

    def test_someone_elses_pdf_is_filed_as_other_with_a_warning(self, tmp_path):
        from ingest.extract import extract

        info = {"Title": "A Paper", "Author": "Jane Economist"}
        result = extract(write_pdf(tmp_path / "f.pdf", [["Text."]], info))
        assert result.meta["authorship"] == "other"
        assert any("Jane Economist" in warning for warning in result.warnings)

    def test_no_author_is_filed_as_other_so_a_reviewer_must_decide(self, tmp_path):
        from ingest.extract import extract

        result = extract(write_pdf(tmp_path / "f.pdf", [["Text."]], {"Title": "T"}))
        assert result.meta["authorship"] == "other"
        assert any("author" in warning for warning in result.warnings)

    def test_the_modality_guess_is_flagged_for_review(self, tmp_path):
        from ingest.extract import extract

        # A PDF can be a syllabus, a paper, a letter or a book; nothing in the file says
        # which, and #41's modality-aware training depends on it being right.
        result = extract(write_pdf(tmp_path / "f.pdf", [["Text."]]))
        assert any("modality" in warning for warning in result.warnings)


class TestNoTextLayer:
    def test_a_fully_scanned_pdf_is_refused_and_deferred_to_ocr(self, tmp_path):
        from ingest.extract import extract

        result = extract(write_pdf(tmp_path / "scan.pdf", [[], []]))
        assert result.documents == []
        assert result.confidence == 0.0
        assert any("OCR" in warning for warning in result.warnings)

    def test_scanned_pages_inside_a_text_pdf_are_named_and_lower_confidence(self, tmp_path):
        from ingest.extract import extract

        result = extract(write_pdf(tmp_path / "mixed.pdf", [["Typed."], [], ["Typed."], []]))
        assert len(result.documents) == 1
        assert result.confidence == pytest.approx(0.5)
        (warning,) = [w for w in result.warnings if "OCR" in w]
        assert "2, 4" in warning and "of 4" in warning

    def test_a_page_of_only_a_page_number_counts_as_no_text(self, tmp_path):
        from ingest.extract import extract

        # A scanned page often still carries a typeset folio; it is not a text layer.
        result = extract(write_pdf(tmp_path / "mixed.pdf", [["Typed prose."], ["7"]]))
        assert result.confidence == pytest.approx(0.5)


class TestUnreadableInput:
    def test_a_password_protected_pdf_is_refused_not_cracked(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "locked.pdf"
        path.write_bytes(encrypted(build_pdf([["Secret."]], HIS), user_password="secret"))
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0
        assert any("password" in warning for warning in result.warnings)

    def test_a_pdf_with_only_an_owner_password_opens_normally(self, tmp_path):
        from ingest.extract import extract

        # Permissions-only encryption (empty user password) is how many ordinary PDFs
        # ship; any reader opens them, so refusing would lose real material for nothing.
        path = tmp_path / "restricted.pdf"
        path.write_bytes(encrypted(build_pdf([["Open text."]], HIS), user_password=""))
        result = extract(path)
        assert "Open text." in result.documents[0]["text"]

    def test_a_corrupt_file_is_refused_without_raising(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "broken.pdf"
        path.write_bytes(b"this is not a pdf")
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0
        assert result.warnings


@pytest.fixture
def without_pypdf(monkeypatch):
    """Simulate an install without the ``ingest`` extra: ``import pypdf`` fails."""
    monkeypatch.setitem(sys.modules, "pypdf", None)


class TestMissingDependency:
    def test_extract_raises_missing_dependency_with_the_install_hint(self, tmp_path, without_pypdf):
        from ingest.extract import MissingDependency, extract

        path = write_pdf(tmp_path / "notes.pdf", [["Text."]])
        with pytest.raises(MissingDependency, match=r"\.\[ingest\]"):
            extract(path)

    def test_scan_inbox_skips_the_file_and_keeps_going(self, tmp_path, without_pypdf):
        from ingest.queue import load_queue, scan_inbox

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        write_pdf(inbox / "notes.pdf", [["Text."]])
        (inbox / "letter.txt").write_text("Dear family, a letter.")
        notices: list[str] = []
        counts = scan_inbox(inbox, tmp_path / "queue", notices=notices)
        assert counts == {"staged": 1, "skipped": 1, "duplicates": 0}
        # Nothing stale is left in the queue: after installing, the PDF stages for real.
        assert [item["original"] for item in load_queue(tmp_path / "queue")] == [
            str(inbox / "letter.txt")
        ]
        (notice,) = notices
        assert "notes.pdf" in notice and ".[ingest]" in notice

    def test_the_cli_prints_the_install_hint(self, tmp_path, without_pypdf, capsys):
        from ingest.__main__ import main

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        write_pdf(inbox / "notes.pdf", [["Text."]])
        assert main(["--inbox", str(inbox), "--queue", str(tmp_path / "queue")]) == 0
        assert ".[ingest]" in capsys.readouterr().out


class TestQueueIntegration:
    def test_a_pdf_stages_into_the_review_queue(self, tmp_path):
        from ingest.queue import stage_file

        item = stage_file(write_pdf(tmp_path / "notes.pdf", [["Real argument."]]), tmp_path / "q")
        assert item["status"] == "pending"
        assert item["meta"]["title"] == "Notes on Money"
        assert "Real argument." in item["documents"][0]["text"]

    def test_two_different_scans_both_reach_review(self, tmp_path):
        from ingest.queue import load_queue, scan_inbox

        # Both extract to no text. Keyed on the empty text they would share one content
        # hash, and the second scan would be reported "already queued" — never reviewed.
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        write_pdf(inbox / "scan-a.pdf", [[]], {"Title": "Lecture 1"})
        write_pdf(inbox / "scan-b.pdf", [[], []], {"Title": "Lecture 2"})
        counts = scan_inbox(inbox, tmp_path / "queue")
        assert counts == {"staged": 2, "skipped": 0, "duplicates": 0}
        hashes = {item["content_hash"] for item in load_queue(tmp_path / "queue")}
        assert len(hashes) == 2

    def test_re_dropping_the_same_scan_is_still_a_no_op(self, tmp_path):
        from ingest.queue import stage_file

        scan = write_pdf(tmp_path / "scan.pdf", [[]])
        assert stage_file(scan, tmp_path / "queue") is not None
        assert stage_file(scan, tmp_path / "queue") is None
