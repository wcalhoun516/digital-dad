"""Prepare training data from the scraped corpus.

Outputs:
  - data/training/finetune.jsonl   — raw text, one JSON per line (all articles)
  - data/training/instruct.jsonl   — chat message format for instruction fine-tuning
  - data/training/corpus.txt       — concatenated plain text, chronological
  - data/training/metadata.csv     — article metadata as CSV

Quality filtering:
  Articles with word_count < 400 are excluded from instruct.jsonl (kept in finetune.jsonl).
  If linguistics.json exists, articles with type_token_ratio < 0.3 are also excluded from instruct.
"""

import csv
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
TRAINING_DIR = DATA_DIR / "training"
MANIFEST_PATH = DATA_DIR / "manifest.json"
LINGUISTICS_PATH = DATA_DIR / "analysis" / "linguistics.json"

SYSTEM_PROMPT = (
    "You are Dr. George Calhoun, a Forbes technology analyst and academic. "
    "You write incisive, data-driven analysis on telecommunications, semiconductors, "
    "technology policy, ESG, nuclear energy, and the intersection of economics and innovation. "
    "Your style is rigorous but accessible, often contrarian, and grounded in evidence. "
    "Write in first person, as Dr. Calhoun would."
)


def _article_to_topic(title: str) -> str:
    """Derive a writing prompt topic from an article title."""
    # Strip common leading question/article words
    topic = re.sub(r"^(why|how|what|when|where|is|are|the|a|an)\s+", "", title, flags=re.IGNORECASE)
    # Strip trailing question marks
    topic = topic.rstrip("?").strip()
    return topic or title


def run():
    if not MANIFEST_PATH.exists():
        print(f"Error: No manifest found at {MANIFEST_PATH}. Run `make scrape` first.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text())
    articles = manifest.get("articles", [])

    if not articles:
        print("No articles in manifest.")
        return

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    # Load TTR data from linguistics analysis if available
    ttr_by_slug: dict[str, float] = {}
    if LINGUISTICS_PATH.exists():
        try:
            ling = json.loads(LINGUISTICS_PATH.read_text())
            for a in ling.get("per_article", []):
                if a.get("slug") and a.get("type_token_ratio") is not None:
                    ttr_by_slug[a["slug"]] = a["type_token_ratio"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Load raw article data
    loaded = []
    for entry in sorted(articles, key=lambda a: a.get("date", "")):
        raw_path = DATA_DIR / entry["file"]
        if raw_path.exists():
            article = json.loads(raw_path.read_text())
            loaded.append((entry, article))

    print(f"Preparing training data from {len(loaded)} articles...")

    # Quality check for instruct format
    def _is_quality(entry: dict, article: dict) -> bool:
        wc = entry.get("word_count") or article.get("word_count") or 0
        if wc < 400:
            return False
        slug = entry.get("slug", "")
        ttr = ttr_by_slug.get(slug)
        if ttr is not None and ttr < 0.3:
            return False
        return True

    # 1. JSONL for fine-tuning (all articles, raw text)
    jsonl_path = TRAINING_DIR / "finetune.jsonl"
    with open(jsonl_path, "w") as f:
        for entry, article in loaded:
            body = article.get("body", "").strip()
            if body:
                f.write(json.dumps({"text": body}, ensure_ascii=False) + "\n")
    print(f"  JSONL (raw): {jsonl_path}  ({len(loaded)} articles)")

    # 2. Instruction-following JSONL (quality-filtered, chat message format)
    instruct_path = TRAINING_DIR / "instruct.jsonl"
    instruct_count = 0
    excluded_count = 0
    with open(instruct_path, "w") as f:
        for entry, article in loaded:
            body = article.get("body", "").strip()
            if not body:
                continue
            if not _is_quality(entry, article):
                excluded_count += 1
                continue
            title = article.get("title") or entry.get("title") or "Untitled"
            topic = _article_to_topic(title)
            record = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Write an analysis of {topic}."},
                    {"role": "assistant", "content": body},
                ]
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            instruct_count += 1
    print(f"  JSONL (instruct): {instruct_path}  ({instruct_count} articles, {excluded_count} excluded by quality filter)")

    # 3. Combined plain text corpus
    corpus_path = TRAINING_DIR / "corpus.txt"
    with open(corpus_path, "w") as f:
        for entry, article in loaded:
            title = article.get("title", entry.get("title", "Untitled"))
            date = (article.get("date", "") or entry.get("date", ""))[:10]
            body = article.get("body", "").strip()
            if body:
                f.write(f"# {title}\n")
                f.write(f"Date: {date}\n\n")
                f.write(body)
                f.write("\n\n---\n\n")
    print(f"  Corpus: {corpus_path}")

    # 4. Metadata CSV
    csv_path = TRAINING_DIR / "metadata.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "title", "date", "word_count", "tags", "url", "quality"])
        for entry, article in loaded:
            writer.writerow([
                entry.get("slug", ""),
                entry.get("title", ""),
                (entry.get("date", "") or "")[:10],
                entry.get("word_count", 0),
                "|".join(entry.get("tags", [])),
                entry.get("url", ""),
                "ok" if _is_quality(entry, article) else "filtered",
            ])
    print(f"  CSV: {csv_path}")

    print(f"\nTraining data ready: {len(loaded)} total, {instruct_count} quality articles for instruct tuning")


if __name__ == "__main__":
    run()
