"""Shared utilities for the analysis pipeline."""

import json
import logging
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
ANALYSIS_DIR = DATA_DIR / "analysis"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the shared analysis logger.

    Mirrors ``scraper/utils.py``: one named logger, a single StreamHandler, and an
    idempotent handler guard so repeated calls (module import + a CLI ``--verbose``
    tweak) never stack duplicate handlers. Unknown level strings fall back to INFO.
    """
    logger = logging.getLogger("digital-dad.analysis")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


log = setup_logging()


def load_manifest() -> dict:
    """Load the scraper manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No manifest found at {MANIFEST_PATH}. Run `make scrape` first."
        )
    return json.loads(MANIFEST_PATH.read_text())


def dedupe_manifest_entries(entries: list[dict]) -> list[dict]:
    """Keep one manifest entry per raw ``file``, in first-seen order.

    The scraper historically upserted on URL, so an article rediscovered under a URL
    variant appended a second entry naming the *same* raw file (23 such http/https twins
    are still in the corpus). Entries with no ``file`` are passed through — they can't
    name a document, and the caller skips them anyway.
    """
    seen: set[str] = set()
    unique = []
    for entry in entries:
        path = entry.get("file") or ""
        if path and path in seen:
            continue
        seen.add(path)
        unique.append(entry)
    return unique


def load_articles() -> list[dict]:
    """Load all raw article JSON files referenced in the manifest, one per file."""
    manifest = load_manifest()
    articles = []
    for entry in dedupe_manifest_entries(manifest["articles"]):
        if not entry.get("file"):
            continue
        path = DATA_DIR / entry["file"]
        if path.exists():
            article = json.loads(path.read_text())
            articles.append(article)
    return sorted(articles, key=lambda a: a.get("date", ""))


def provenance_for_slugs(slugs, manifest: dict | None = None) -> list[dict]:
    """Provenance blocks for the named corpus entries, for the T3 guard to rule on.

    Legacy entries — every one in today's manifest, since roadmap #29's data migration is
    still pending — are resolved through ``ingest.provenance.migrate_articles``, which is
    the repo's own statement of what they are: scraped, public, Forbes-licensed. A slug the
    manifest has never heard of yields a bare block with no ``privacy``, which the guard
    reads as private.
    """
    from ingest.provenance import migrate_articles

    manifest = manifest if manifest is not None else load_manifest()
    migrated, _ = migrate_articles(manifest.get("articles", []))
    known = {entry.get("slug", ""): entry.get("provenance", {}) for entry in migrated}

    blocks, seen = [], set()
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        blocks.append(known.get(slug) or {"source_id": slug})
    return blocks


def corpus_provenance(manifest: dict | None = None) -> list[dict]:
    """Provenance for the whole corpus — for callers whose prompt could quote any article."""
    manifest = manifest if manifest is not None else load_manifest()
    slugs = [entry.get("slug", "") for entry in manifest.get("articles", [])]
    return provenance_for_slugs(slugs, manifest=manifest)


# Wire-service junk embedded in scraped Forbes bodies. Stock-photo captions sit at
# article tops, so they land disproportionately at the START of a chunk — exactly where
# a model learns how to begin a piece. Measured 2026-09-19: 22% of training passages.
_PHOTO_CREDIT = re.compile(r"\((?:Photo|Picture)\s*(?:by|credit|:)[^)]{0,200}\)", re.I)
_AGENCY_CREDIT = re.compile(
    r"AFP PHOTO/\S+(?:\s+\S+)?"           # AFP PHOTO/Emmanuel Dunand
    r"|REUTERS/\S+"                         # REUTERS/Kim
    r"|[\w.\-]*(?:/[\w.\-]+)*\s*via Getty Images"
    r"|\bGetty Images\b"
    r"|RESTRICTED TO EDITORIAL USE[^()]{0,200}?(?=\(|$)"
    r"|MANDATORY CREDIT[^()]{0,200}?(?=\(|$)"
    r"|NO MARKETING NO ADVERTISING CAMPAIGNS",
    re.I,
)
_TRUNCATION = re.compile(r"\[\+\]")
# "MADRID, SPAIN - 2019/04/03:" / "WASHINGTON, DC - JULY 15:" / "TAIPEI, TAIWAN:"
_DATELINE = re.compile(
    r"\b[A-Z][A-Z.'\- ]{1,30}(?:,\s*[A-Z][A-Z.'\- ]{1,30})?\s*[-\u2013:]\s"
)
_CAPTION_WINDOW = 400   # a caption never runs longer than this; bounds any mistake


def strip_wire_boilerplate(text: str) -> str:
    """Remove stock-photo captions and agency credits from a scraped article body.

    Deliberately conservative: a greedy cleaner that eats his prose is worse than
    leaving captions in. A dateline is only treated as a caption when the window after
    it also carries a caption *signal* (a ``[+]`` truncation marker or an agency
    credit) — so "CPI, PCE - these two measures diverged" is left alone.
    """
    if not text:
        return ""

    # Datelines first: the [+] and credit markers are the signal, so remove spans
    # before the markers themselves are stripped.
    out, pos = [], 0
    for m in _DATELINE.finditer(text):
        if m.start() < pos:
            continue
        window = text[m.start():m.start() + _CAPTION_WINDOW]
        signal = _TRUNCATION.search(window) or _AGENCY_CREDIT.search(window)
        if not signal:
            continue
        # End the caption at the first sentence break after the signal. If there is
        # no sentence break inside the window, FAIL CLOSED: cut only through the
        # signal itself. Deleting the whole window would swallow the prose that
        # follows — which it did, eating a real sentence about Minsheng's CEO.
        # A caption is its own block, so a blank line ends it; otherwise a sentence
        # break does. Match "." followed by ANY whitespace — the real corpus ends
        # captions with a newline, and looking only for ". " skipped past the
        # sentence that followed and ate it.
        rest = window[signal.end():]
        stop = re.search(r"\n\s*\n|\.\s", rest)
        end = m.start() + signal.end() + (stop.end() if stop else 0)
        out.append(text[pos:m.start()])
        pos = end
    out.append(text[pos:])
    text = "".join(out)

    text = _PHOTO_CREDIT.sub(" ", text)
    text = _AGENCY_CREDIT.sub(" ", text)
    text = _TRUNCATION.sub(" ", text)
    # Collapse horizontal runs only — PARAGRAPH BREAKS MUST SURVIVE. Flattening \n\n
    # here silently broke training/prepare.py's repeated-paragraph footer stripper,
    # which splits on blank lines; its test caught it.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_text(text: str) -> str:
    """Basic text cleaning for analysis."""
    text = strip_wire_boilerplate(text)

    # Remove common Forbes boilerplate
    boilerplate = [
        r"Follow me on Twitter.*",
        r"I am a.*?contributor.*?\.",
        r"Read my.*?Forbes.*?\.",
        r"This is an opinion.*?\.",
        r"The opinions expressed.*?\.",
    ]
    for pattern in boilerplate:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def chunk_text(text: str, max_tokens: int = 3000, overlap: int = 200) -> list[str]:
    """Split text into chunks that fit within a token budget.

    Uses a rough 1 token ≈ 4 chars heuristic.
    """
    max_chars = max_tokens * 4
    # An overlap at or above the chunk size would move the cursor backwards each
    # iteration and never terminate; half a chunk is the most that still advances.
    overlap_chars = min(overlap * 4, max_chars // 2)

    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Try to break at a sentence boundary
        if end < len(text):
            last_period = text.rfind(".", start + max_chars // 2, end)
            if last_period > start:
                end = last_period + 1
        chunks.append(text[start:end].strip())
        start = end - overlap_chars

    return chunks


def save_analysis(filename: str, data: dict | list) -> Path:
    """Save analysis results to the analysis directory."""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path
