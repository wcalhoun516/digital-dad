"""EPUB handler — stdlib only (roadmap #35).

An EPUB is a ZIP of XHTML: ``META-INF/container.xml`` points at the ``.opf`` package
document, whose ``<manifest>`` maps ids to hrefs and whose ``<spine>`` gives the reading
order. ``zipfile`` + ``xml.etree`` + ``html.parser`` cover all of it, so the
zero-dependency core stays intact and CI needs no extra install.

Reading order comes from the spine, never from ZIP entry order — real EPUBs store their
entries in arbitrary order, and a book read out of sequence is worse than no book.
"""

import posixpath
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from analysis.utils import clean_text
from ingest.extract import ExtractResult, empty_meta, register

CONTAINER_PATH = "META-INF/container.xml"
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


@register(".epub")
def extract_epub(path: Path) -> ExtractResult:
    """Extract one document per spine item from an ``.epub`` file."""
    path = Path(path)

    with zipfile.ZipFile(path) as archive:
        container = archive.read(CONTAINER_PATH).decode("utf-8", errors="replace")
        opf_path = opf_path_from_container(container)
        opf_dir = posixpath.dirname(opf_path)
        opf_xml = archive.read(opf_path).decode("utf-8", errors="replace")

        documents: list[dict] = []
        warnings: list[str] = []
        for ordinal, href in enumerate(spine_hrefs(opf_xml)):
            member = posixpath.normpath(posixpath.join(opf_dir, href))
            xhtml = archive.read(member).decode("utf-8", errors="replace")
            title, text = xhtml_to_document(xhtml)
            title = title or Path(href).stem

            reason = front_matter_reason(title, text)
            if reason:
                warnings.append(f"dropped {title!r} — {reason}")
                continue
            # Ordinal is the spine position, so a gap in the sequence shows where a drop
            # happened rather than hiding it behind renumbering.
            documents.append({"title": title, "text": text, "ordinal": ordinal})

    meta = empty_meta(path.stem)
    if not documents:
        warnings.append("no prose chapters recovered")
        return ExtractResult(documents=[], meta=meta, confidence=0.0, warnings=warnings)
    return ExtractResult(
        documents=documents,
        meta=meta,
        confidence=0.8 if warnings else 1.0,
        warnings=warnings,
    )
