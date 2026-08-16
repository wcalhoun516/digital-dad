"""Interactive review of the ingest queue (roadmap #31).

Mirrors ``analysis/adjudicate.py``: iterate unreviewed items, prompt, write the decision
back immediately so progress survives a Ctrl-C.

Two rules make this usable rather than tedious:
  * Review is per **source**, not per document — a book prompts once, not forty times.
  * Rejects are never deleted; they keep their reason so a bad extraction is recoverable.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from ingest.provenance import (
    AUTHORSHIPS,
    MODALITIES,
    PRIVACIES,
    default_provenance,
)
from ingest.queue import QUEUE_DIR, load_queue, save_item

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "manifest.json"


def queue_summary(items: list[dict]) -> dict:
    """Count queue items by status."""
    return {
        "total": len(items),
        "pending": sum(i.get("status") == "pending" for i in items),
        "accepted": sum(i.get("status") == "accepted" for i in items),
        "rejected": sum(i.get("status") == "rejected" for i in items),
    }


def print_report(items: list[dict]) -> None:
    """Print a queue summary. Read-only — safe for the nightly agent to run."""
    summary = queue_summary(items)
    print(
        f"Queue: {summary['total']} item(s) — {summary['pending']} pending, "
        f"{summary['accepted']} accepted, {summary['rejected']} rejected."
    )
    for item in items:
        if item.get("status") != "pending":
            continue
        warn = f"  ⚠ {len(item['warnings'])}" if item.get("warnings") else ""
        title = item.get("meta", {}).get("title") or "(untitled)"
        print(f"  [{item.get('confidence', 0):.2f}] {item['id']}  {title[:48]}{warn}")


def accept_item(item: dict, manifest: dict) -> dict:
    """Append one accepted queue item to the manifest as a document entry."""
    meta = item["meta"]
    provenance = default_provenance(
        source_id=item["id"],
        modality=meta.get("modality", "letter"),
        authorship=meta.get("authorship", "george"),
        privacy=meta.get("privacy", "private"),
        license=meta.get("license", "personal"),
        acquisition={
            "method": "ingest",
            "ref": item.get("original", ""),
            "at": date.today().isoformat(),
        },
        date_confidence=meta.get("date_confidence", "unknown"),
    )
    word_count = sum(len(doc.get("text", "").split()) for doc in item["documents"])
    manifest.setdefault("articles", []).append(
        {
            "slug": item["id"],
            "title": meta.get("title", ""),
            "date": meta.get("date", ""),
            "url": "",
            "tags": [],
            "word_count": word_count,
            "content_hash": item.get("content_hash", ""),
            "provenance": provenance,
        }
    )
    manifest["total_articles"] = len(manifest["articles"])
    item["status"] = "accepted"
    return manifest


def _show(item: dict) -> None:
    meta = item["meta"]
    print("\n" + "=" * 72)
    for warning in item.get("warnings", []):
        print(f"  ⚠  {warning}")
    print(f"  {item['id']}   confidence {item.get('confidence', 0):.2f}")
    print(f"  TITLE:      {meta.get('title') or '(untitled)'}")
    print(f"  DATE:       {meta.get('date') or '—'} ({meta.get('date_confidence')})")
    print(f"  MODALITY:   {meta.get('modality')}   AUTHORSHIP: {meta.get('authorship')}")
    print(f"  PRIVACY:    {meta.get('privacy')}   DOCUMENTS: {len(item['documents'])}")
    preview = (item["documents"][0]["text"] if item["documents"] else "")[:400]
    print("-" * 72)
    print("  " + preview.replace("\n", "\n  "))
    print("-" * 72)
    print(f"  original: file://{item.get('original', '')}")
    print("  [a]ccept  [e]dit  [r]eject   ([s]kip / [q]uit)")


def _edit(item: dict, input_fn) -> None:
    """Correct the fields worth correcting. Blank input keeps the current value."""
    meta = item["meta"]
    for field_name, vocabulary in (
        ("title", None),
        ("date", None),
        ("modality", MODALITIES),
        ("authorship", AUTHORSHIPS),
        ("privacy", PRIVACIES),
    ):
        hint = f" {sorted(vocabulary)}" if vocabulary else ""
        answer = input_fn(f"  {field_name}{hint} [{meta.get(field_name, '')}]> ").strip()
        if not answer:
            continue
        if vocabulary and answer not in vocabulary:
            print(f"  ! '{answer}' is not valid — keeping {meta.get(field_name)!r}")
            continue
        meta[field_name] = answer
        if field_name == "date":
            # A hand-entered date is a human's best recollection, never authoritative.
            meta["date_confidence"] = "approximate"


def run_cli(
    queue_dir: Path = QUEUE_DIR,
    manifest_path: Path = MANIFEST_PATH,
    limit: int | None = None,
    input_fn=input,
) -> int:
    """Interactive review loop. Writes after every decision so progress is resumable."""
    queue_dir = Path(queue_dir)
    manifest_path = Path(manifest_path)
    items = load_queue(queue_dir)
    if not items:
        print("Queue is empty. Drop files in data/inbox/ and run `make ingest`.")
        return 0

    manifest = json.loads(manifest_path.read_text())
    summary = queue_summary(items)
    print(f"Loaded {summary['total']} item(s) — {summary['pending']} pending.")

    done = 0
    for item in items:
        if item.get("status") != "pending":
            continue
        if limit is not None and done >= limit:
            print(f"\nReached limit of {limit}. Stopping.")
            break

        _show(item)
        choice = input_fn("  decision> ").strip().lower()

        if choice in ("q", "quit"):
            break
        if choice in ("s", "skip", ""):
            continue
        if choice in ("e", "edit"):
            _edit(item, input_fn)
            choice = input_fn("  decision> ").strip().lower()
        if choice in ("r", "reject"):
            item["status"] = "rejected"
            item["reject_reason"] = input_fn("  reason> ").strip()
            save_item(item, queue_dir)
            print("  ✓ rejected")
            done += 1
            continue
        if choice in ("a", "accept"):
            accept_item(item, manifest)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            save_item(item, queue_dir)
            print("  ✓ accepted")
            done += 1
            continue
        print(f"  ! '{choice}' is not a decision — skipping.")

    print(f"\nDone. {done} decision(s) this session.")
    print_report(load_queue(queue_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.review",
        description="Review staged ingest items and accept them into the corpus.",
    )
    parser.add_argument("--queue", type=Path, default=QUEUE_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the queue summary and exit. Read-only; changes nothing.",
    )
    args = parser.parse_args(argv)

    if args.report:
        print_report(load_queue(args.queue))
        return 0
    return run_cli(queue_dir=args.queue, manifest_path=args.manifest, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
