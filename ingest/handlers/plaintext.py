"""Plaintext and Markdown handler — stdlib only (roadmap #30)."""

from pathlib import Path

from ingest.extract import ExtractResult, empty_meta, register


@register(".txt", ".md")
def extract_plaintext(path: Path) -> ExtractResult:
    """Read a text file as a single document.

    A Markdown ``# H1`` on the first non-blank line becomes the title; otherwise the
    filename stem is used. An effectively-empty file is surfaced as a warning at zero
    confidence rather than silently entering the queue.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()

    title = Path(path).stem
    for line in stripped.splitlines():
        if line.strip():
            if line.lstrip().startswith("# "):
                title = line.lstrip()[2:].strip()
            break

    meta = empty_meta(title)
    if not stripped:
        return ExtractResult(
            documents=[], meta=meta, confidence=0.0, warnings=["file is empty"]
        )

    return ExtractResult(
        documents=[{"title": title, "text": text, "ordinal": 0}],
        meta=meta,
        confidence=1.0,
        warnings=[],
    )
