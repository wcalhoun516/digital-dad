"""Prepare training data from the scraped corpus.

Outputs:
  - data/training/finetune.jsonl  — one JSON object per line for fine-tuning
  - data/training/corpus.txt      — concatenated plain text, chronological
  - data/training/metadata.csv    — article metadata as CSV
"""

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
TRAINING_DIR = DATA_DIR / "training"
MANIFEST_PATH = DATA_DIR / "manifest.json"


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

    # Load raw article data
    loaded = []
    for entry in sorted(articles, key=lambda a: a.get("date", "")):
        raw_path = DATA_DIR / entry["file"]
        if raw_path.exists():
            article = json.loads(raw_path.read_text())
            loaded.append((entry, article))

    print(f"Preparing training data from {len(loaded)} articles...")

    # 1. JSONL for fine-tuning
    jsonl_path = TRAINING_DIR / "finetune.jsonl"
    with open(jsonl_path, "w") as f:
        for entry, article in loaded:
            body = article.get("body", "").strip()
            if body:
                line = json.dumps({"text": body}, ensure_ascii=False)
                f.write(line + "\n")
    print(f"  JSONL: {jsonl_path}")

    # 2. Combined plain text corpus
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

    # 3. Metadata CSV
    csv_path = TRAINING_DIR / "metadata.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "title", "date", "word_count", "tags", "url"])
        for entry, article in loaded:
            writer.writerow([
                entry.get("slug", ""),
                entry.get("title", ""),
                (entry.get("date", "") or "")[:10],
                entry.get("word_count", 0),
                "|".join(entry.get("tags", [])),
                entry.get("url", ""),
            ])
    print(f"  CSV: {csv_path}")

    print(f"\nTraining data ready: {len(loaded)} articles")


if __name__ == "__main__":
    run()
