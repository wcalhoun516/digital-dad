"""EPUB handler — stdlib only (roadmap #35).

An EPUB is a ZIP of XHTML: ``META-INF/container.xml`` points at the ``.opf`` package
document, whose ``<manifest>`` maps ids to hrefs and whose ``<spine>`` gives the reading
order. ``zipfile`` + ``xml.etree`` + ``html.parser`` cover all of it, so the
zero-dependency core stays intact and CI needs no extra install.

Reading order comes from the spine, never from ZIP entry order — real EPUBs store their
entries in arbitrary order, and a book read out of sequence is worse than no book.
"""

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from analysis.utils import clean_text
from ingest.extract import ExtractResult, empty_meta, register

CONTAINER_PATH = "META-INF/container.xml"
ENCRYPTION_PATH = "META-INF/encryption.xml"
# Detect and refuse. Circumventing DRM is out of scope by design — the owner buys
# DRM-free copies, and this message is what tells him which file needs replacing.
DRM_WARNING = "this file appears to be DRM-protected — a DRM-free copy is required"
_BLOCK_TAGS = frozenset({"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"})
_HEADING_TAGS = ("h1", "h2", "h3")
_SILENT_TAGS = frozenset({"script", "style", "head"})

# A chapter of prose runs to thousands of characters; a dedication, epigraph or half-title
# runs to a few dozen. The threshold sits well below any real chapter so the rule errs
# toward keeping — a dropped chapter is unrecoverable, a kept front-matter page is not.
MIN_CHAPTER_CHARS = 500

_NON_PROSE_TITLES = frozenset(
    {
        "about the author",
        "acknowledgements",
        "acknowledgments",
        "colophon",
        "contents",
        "copyright",
        "cover",
        "dedication",
        "epigraph",
        "front matter",
        "half title",
        "index",
        "permissions",
        "table of contents",
        "title page",
    }
)
_FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_YEAR_ONLY = re.compile(r"^\d{4}$")
_HIS_NAME = "calhoun"

_NON_PROSE_PREFIXES = (
    "about the author",
    "also by ",
    "copyright",
    "index of ",
    "praise for ",
)


def front_matter_reason(title: str, text: str) -> str:
    """Why this spine item is not his prose, or "" to keep it.

    Front and back matter — copyright pages, dedications, indexes, author bios — would
    pollute a voice fine-tune with text he did not write, so it is dropped. Every drop is
    reported as a warning; nothing is removed silently.
    """
    normalized = " ".join(title.lower().replace("_", " ").split()).strip(".:—- ")
    if normalized in _NON_PROSE_TITLES or normalized.startswith(_NON_PROSE_PREFIXES):
        return "non-prose title"
    if len(text) < MIN_CHAPTER_CHARS:
        return f"only {len(text)} characters"
    return ""


class _ChapterParser(HTMLParser):
    """Collects chapter text and its first heading, dropping markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._heading: list[str] = []
        self._capturing_heading = False
        self._suppress_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SILENT_TAGS:
            self._suppress_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")
        if tag in _HEADING_TAGS and not self._heading:
            self._capturing_heading = True

    def handle_endtag(self, tag):
        if tag in _SILENT_TAGS:
            self._suppress_depth = max(0, self._suppress_depth - 1)
            return
        if tag in _HEADING_TAGS:
            self._capturing_heading = False
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data):
        if self._suppress_depth:
            return
        self._parts.append(data)
        if self._capturing_heading:
            self._heading.append(data)

    @property
    def title(self) -> str:
        return clean_text("".join(self._heading))

    @property
    def text(self) -> str:
        """Paragraphs, each whitespace-normalized, separated by a blank line.

        ``clean_text`` collapses *all* whitespace to single spaces, so it is applied per
        paragraph rather than to the chapter — paragraph structure is what plan 0009's
        passage-level training records are cut on, and flattening it here would lose it.
        """
        paragraphs = [clean_text(block) for block in "".join(self._parts).split("\n\n")]
        return "\n\n".join(block for block in paragraphs if block)


def xhtml_to_document(xhtml: str) -> tuple[str, str]:
    """``(title, text)`` for one chapter. Title is its first heading, or ""."""
    parser = _ChapterParser()
    parser.feed(xhtml)
    parser.close()
    return parser.title, parser.text


def _localname(tag: str) -> str:
    """The tag without its ``{namespace}`` prefix — EPUBs vary on whether they use one."""
    return tag.rsplit("}", 1)[-1]


def _find_all(root, name: str):
    return [node for node in root.iter() if _localname(node.tag) == name]


def opf_path_from_container(container_xml: str) -> str:
    """The package document's path, from ``META-INF/container.xml``."""
    root = ElementTree.fromstring(container_xml)
    for rootfile in _find_all(root, "rootfile"):
        full_path = rootfile.get("full-path")
        if full_path:
            return full_path
    return ""


def spine_hrefs(opf_xml: str) -> list[str]:
    """Manifest hrefs in **spine** order, relative to the OPF's own directory."""
    root = ElementTree.fromstring(opf_xml)
    manifest = {
        item.get("id"): item.get("href", "")
        for item in _find_all(root, "item")
        if item.get("id")
    }
    hrefs = []
    for itemref in _find_all(root, "itemref"):
        href = manifest.get(itemref.get("idref"), "")
        if href:
            hrefs.append(href)
    return hrefs


def _dc_field(opf_xml: str, name: str) -> str:
    """A Dublin Core ``<metadata>`` value from the OPF, or ""."""
    root = ElementTree.fromstring(opf_xml)
    for node in _find_all(root, name):
        if node.text and node.text.strip():
            return " ".join(node.text.split())
    return ""


def _normalize_date(raw: str) -> tuple[str, str]:
    """``(date, date_confidence)`` from a Dublin Core date.

    EPUB dates are only loosely specified: full ISO timestamps, plain dates and bare years
    all occur. A bare year is kept as a year and marked approximate rather than invented
    into a January 1st that a reader would take literally.
    """
    raw = raw.strip()
    if _FULL_DATE.match(raw):
        return raw[:10], "exact"
    if _YEAR_ONLY.match(raw):
        return raw, "approximate"
    return "", "unknown"


def _refused(path: Path, reason: str) -> ExtractResult:
    """Refuse a file we cannot read, at zero confidence, without raising.

    A whole ingest run must not die on one bad file — the queue stages this as a
    zero-confidence item and a human sees the reason in review.
    """
    return ExtractResult(documents=[], meta=empty_meta(path.stem), confidence=0.0,
                         warnings=[reason])


@register(".epub")
def extract_epub(path: Path) -> ExtractResult:
    """Extract one document per spine item from an ``.epub`` file."""
    path = Path(path)

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if ENCRYPTION_PATH in names:
                return _refused(path, DRM_WARNING)

            if CONTAINER_PATH not in names:
                return _refused(path, f"no {CONTAINER_PATH} — this is not a readable EPUB")
            container = archive.read(CONTAINER_PATH).decode("utf-8", errors="replace")
            opf_path = opf_path_from_container(container)
            if opf_path not in names:
                return _refused(path, f"package document {opf_path!r} is missing")
            opf_dir = posixpath.dirname(opf_path)
            opf_xml = archive.read(opf_path).decode("utf-8", errors="replace")

            documents: list[dict] = []
            warnings: list[str] = []
            for ordinal, href in enumerate(spine_hrefs(opf_xml)):
                member = posixpath.normpath(posixpath.join(opf_dir, href))
                if member not in names:
                    warnings.append(f"spine item {href!r} is missing from the archive")
                    continue
                xhtml = archive.read(member).decode("utf-8", errors="replace")
                title, text = xhtml_to_document(xhtml)
                title = title or Path(href).stem

                reason = front_matter_reason(title, text)
                if reason:
                    warnings.append(f"dropped {title!r} — {reason}")
                    continue
                # Ordinal is the spine position, so a gap in the sequence shows where a
                # drop happened rather than hiding it behind renumbering.
                documents.append({"title": title, "text": text, "ordinal": ordinal})
    except zipfile.BadZipFile:
        return _refused(path, "not a ZIP archive — the file is corrupt or not an EPUB")
    except ElementTree.ParseError as error:
        # Unparseable XML in a syntactically valid ZIP is the other shape DRM takes.
        return _refused(path, f"package document is unreadable ({error}) — {DRM_WARNING}")

    book_title = _dc_field(opf_xml, "title")
    creator = _dc_field(opf_xml, "creator")
    meta = empty_meta(book_title or path.stem)
    meta["modality"] = "book"
    meta["date"], meta["date_confidence"] = _normalize_date(_dc_field(opf_xml, "date"))

    if not book_title:
        warnings.append("no title in the package metadata — using the filename")
    if not creator:
        warnings.append("no author in the package metadata — a reviewer must set authorship")
        meta["authorship"] = "other"
    elif _HIS_NAME not in creator.lower():
        # An ebook of someone else's book must never enter the corpus as his voice. The
        # review CLI is the gate; this warning is what makes a reviewer look at it.
        warnings.append(f"author is {creator!r}, not Calhoun — filed as authorship 'other'")
        meta["authorship"] = "other"

    if not documents:
        warnings.append("no prose chapters recovered")
        return ExtractResult(documents=[], meta=meta, confidence=0.0, warnings=warnings)
    return ExtractResult(
        documents=documents,
        meta=meta,
        confidence=0.8 if warnings else 1.0,
        warnings=warnings,
    )
