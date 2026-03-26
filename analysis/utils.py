"""Shared utilities for the analysis pipeline."""

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
ANALYSIS_DIR = DATA_DIR / "analysis"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def load_manifest() -> dict:
    """Load the scraper manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No manifest found at {MANIFEST_PATH}. Run `make scrape` first."
        )
    return json.loads(MANIFEST_PATH.read_text())


def load_articles() -> list[dict]:
    """Load all raw article JSON files referenced in the manifest."""
    manifest = load_manifest()
    articles = []
    for entry in manifest["articles"]:
        path = DATA_DIR / entry["file"]
        if path.exists():
            article = json.loads(path.read_text())
            articles.append(article)
    return sorted(articles, key=lambda a: a.get("date", ""))


def clean_text(text: str) -> str:
    """Basic text cleaning for analysis."""
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
    overlap_chars = overlap * 4

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
