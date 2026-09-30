"""PDF handler — the first user of the opt-in ``ingest`` extra (roadmap #34).

A PDF has no paragraphs, only glyphs placed on a page, so structure is recovered from
geometry: pypdf's *layout* extraction renders vertical gaps as blank lines, which is what
separates one paragraph from the next. The plain mode drops those gaps, and paragraph
structure is what plan 0009's passage-level training records are cut on.

``pypdf`` is imported lazily, inside the handler. Without it this module still registers
``.pdf`` and the run skips the file with an install hint (``MissingDependency``) — the
stdlib-only core, and every other format, keep working.

A page with no text layer is a scan. It is never silently dropped: the page numbers go in a
warning that defers them to OCR (#36), and the confidence is the fraction of pages read.
"""

import re
from pathlib import Path

from ingest.extract import INSTALL_HINT, ExtractResult, MissingDependency, empty_meta, register

_HIS_NAME = "calhoun"
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# A folio: "12", "Page 12", "xiv". Only ever tested against the first or last line of a
# page — a bare number *inside* the prose (a year on its own line) is his text.
_FOLIO = re.compile(r"^(page\s+)?(\d{1,4}|[ivxlc]{1,7})$", re.IGNORECASE)

PASSWORD_WARNING = "this PDF is password-protected — an unprotected copy is required"


def _refused(path: Path, reason: str, meta: dict | None = None) -> ExtractResult:
    """Refuse a file we cannot read, at zero confidence, without raising.

    Same contract as the EPUB handler: one bad file stages as a zero-confidence item a
    human sees in review; it never kills the run.
    """
    return ExtractResult(
        documents=[], meta=meta or empty_meta(path.stem), confidence=0.0, warnings=[reason]
    )


def page_paragraphs(layout_text: str) -> list[str]:
    """Paragraphs on one page: wrapped lines rejoined, running folios dropped.

    Whitespace is normalized directly rather than through ``clean_text``, whose Forbes
    boilerplate patterns ("I am a ... contributor.") would eat prose outside a column.
    """
    lines = [line.strip() for line in layout_text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if lines and _FOLIO.match(lines[0]):
        lines.pop(0)
    if lines and _FOLIO.match(lines[-1]):
        lines.pop()
    blocks = _PARAGRAPH_BREAK.split("\n".join(lines))
    return [" ".join(block.split()) for block in blocks if block.strip()]


def _format_pages(numbers: list[int]) -> str:
    return ", ".join(str(number) for number in numbers)


def _info_meta(path: Path, reader, warnings: list[str]) -> dict:
    """Provenance meta from the document-info dictionary, warning on every gap."""
    info = reader.metadata or {}
    title = " ".join(str(info.get("/Title") or "").split())
    author = " ".join(str(info.get("/Author") or "").split())

    meta = empty_meta(title or path.stem)
    if not title:
        warnings.append("no title in the PDF metadata — using the filename")

    try:
        created = reader.metadata.creation_date if reader.metadata else None
    except ValueError:  # a malformed date string is common and not worth failing over
        created = None
    if created:
        # When the *file* was produced, not when he wrote it — hence approximate.
        meta["date"], meta["date_confidence"] = created.date().isoformat(), "approximate"

    if not author:
        warnings.append("no author in the PDF metadata — a reviewer must set authorship")
        meta["authorship"] = "other"
    elif _HIS_NAME not in author.lower():
        warnings.append(f"author is {author!r}, not Calhoun — filed as authorship 'other'")
        meta["authorship"] = "other"

    warnings.append(
        f"modality is a guess ({meta['modality']!r}) — a PDF may be a syllabus, paper, "
        "letter or book; set it in review"
    )
    return meta


@register(".pdf")
def extract_pdf(path: Path) -> ExtractResult:
    """Extract a ``.pdf`` as one document, paragraphs kept, scanned pages reported."""
    path = Path(path)
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise MissingDependency(f"the .pdf handler needs pypdf — {INSTALL_HINT}") from error

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            # An empty user password is permissions-only encryption that any reader opens.
            # Anything else needs the password, and guessing it is out of scope by design.
            return _refused(path, PASSWORD_WARNING)
        pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
        warnings: list[str] = []
        meta = _info_meta(path, reader, warnings)
    except Exception as error:  # noqa: BLE001
        # pypdf's failures on malformed input are not a closed set (read errors, bad
        # streams, missing crypto backends), and one bad file must never end the run.
        return _refused(path, f"not a readable PDF ({type(error).__name__}: {error})")

    paragraphs: list[str] = []
    blank_pages: list[int] = []
    for number, layout_text in enumerate(pages, 1):
        found = page_paragraphs(layout_text)
        if not found:
            blank_pages.append(number)
        paragraphs.extend(found)

    if not paragraphs:
        warnings.insert(
            0,
            f"no text layer on any of {len(pages)} page(s) — this looks like a scan; "
            "it needs OCR (roadmap #36)",
        )
        return ExtractResult(documents=[], meta=meta, confidence=0.0, warnings=warnings)

    if blank_pages:
        warnings.insert(
            0,
            f"no text layer on page(s) {_format_pages(blank_pages)} of {len(pages)} — "
            "likely scanned; they need OCR (roadmap #36)",
        )
    # Metadata gaps are warned about but not scored: most PDFs carry no author or title,
    # and a score every file shares tells a reviewer nothing. Confidence is only the share
    # of pages whose text we actually recovered.
    return ExtractResult(
        documents=[{"title": meta["title"], "text": "\n\n".join(paragraphs), "ordinal": 0}],
        meta=meta,
        confidence=(len(pages) - len(blank_pages)) / len(pages),
        warnings=warnings,
    )
