"""``make ingest`` — scan data/inbox/ and stage everything for review."""

import argparse
from pathlib import Path

from ingest.queue import INBOX_DIR, QUEUE_DIR, scan_inbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description="Extract files from data/inbox/ into the review queue. "
        "Never modifies the corpus — run `make ingest-review` to accept items.",
    )
    parser.add_argument("--inbox", type=Path, default=INBOX_DIR)
    parser.add_argument("--queue", type=Path, default=QUEUE_DIR)
    args = parser.parse_args(argv)

    counts = scan_inbox(args.inbox, args.queue)
    print(
        f"Staged {counts['staged']}, skipped {counts['skipped']} (unsupported), "
        f"{counts['duplicates']} already queued."
    )
    if counts["staged"]:
        print("Review them with: make ingest-review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
