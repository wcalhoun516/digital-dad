"""Stage extracted files into a review queue (roadmap #30).

Extraction never touches the corpus. Everything lands here as pending JSON until a human
accepts it in ``ingest.review``. Re-dropping a file is a no-op: de-duplication reuses the
scraper's ``content_hash`` convention (MD5 of body).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.extract import ExtractResult, UnsupportedFormat, extract, handler_for
from scraper.manifest_dedup import content_hash_for

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INBOX_DIR = DATA_DIR / "inbox"
QUEUE_DIR = DATA_DIR / "ingest" / "queue"


def rejected_dir_for(queue_dir: Path = QUEUE_DIR) -> Path:
    """The quarantine that serves a queue, always its sibling.

    Paired by location rather than configured separately so that pointing anything — the
    console, the CLI, a test — at a different queue moves its rejects along with it.
    """
    return Path(queue_dir).parent / "rejected"


REJECTED_DIR = rejected_dir_for(QUEUE_DIR)


def load_queue(queue_dir: Path = QUEUE_DIR) -> list[dict]:
    """Read every item in one directory, sorted by id. A missing directory is empty."""
    queue_dir = Path(queue_dir)
    if not queue_dir.is_dir():
        return []
    items = [json.loads(p.read_text()) for p in queue_dir.glob("*.json")]
    return sorted(items, key=lambda item: item.get("id", ""))


def load_all(queue_dir: Path = QUEUE_DIR) -> list[dict]:
    """Every item the queue knows about, awaiting a decision or quarantined by one.

    Rejects live in a second directory but are still part of the record: they carry the
    content hashes that keep a re-dropped file from being re-queued, and the count a
    summary reports.
    """
    items = load_queue(queue_dir) + load_queue(rejected_dir_for(queue_dir))
    return sorted(items, key=lambda item: item.get("id", ""))


def save_item(item: dict, queue_dir: Path = QUEUE_DIR) -> Path:
    """Write one queue item, creating the queue directory if needed."""
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{item['id']}.json"
    path.write_text(json.dumps(item, indent=2) + "\n")
    return path


def quarantine(item: dict, queue_dir: Path = QUEUE_DIR) -> Path:
    """Move a decided-against item out of the queue into the quarantine beside it.

    Written before the queue copy is dropped, so an interrupted move leaves the item in two
    places rather than none — a duplicate is recoverable, a rejected extraction may be the
    only copy of the material.
    """
    path = save_item(item, rejected_dir_for(queue_dir))
    (Path(queue_dir) / f"{item['id']}.json").unlink(missing_ok=True)
    return path


def _combined_text(result: ExtractResult) -> str:
    return "\n".join(doc.get("text", "") for doc in result.documents)


def stage_file(path: Path, queue_dir: Path = QUEUE_DIR) -> dict | None:
    """Extract one file into the queue.

    Returns the staged item, or ``None`` when the format is unsupported or the content is
    already queued. Never raises on an unsupported file — a mixed inbox must not fail the
    whole run.
    """
    path = Path(path)
    try:
        result = extract(path)
    except UnsupportedFormat:
        return None

    content_hash = content_hash_for(_combined_text(result))
    existing = {item.get("content_hash") for item in load_all(queue_dir)}
    if content_hash in existing:
        return None

    item = {
        "id": f"{path.stem}-{content_hash[:8]}",
        "status": "pending",
        "original": str(path),
        "content_hash": content_hash,
        "documents": result.documents,
        "meta": result.meta,
        "confidence": result.confidence,
        "warnings": result.warnings,
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_item(item, queue_dir)
    return item


def scan_inbox(inbox: Path = INBOX_DIR, queue_dir: Path = QUEUE_DIR) -> dict:
    """Stage every file in ``inbox``. Returns counts of staged / skipped / duplicates."""
    inbox = Path(inbox)
    counts = {"staged": 0, "skipped": 0, "duplicates": 0}
    if not inbox.is_dir():
        return counts

    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if handler_for(path) is None:
            counts["skipped"] += 1
            continue
        if stage_file(path, queue_dir) is None:
            counts["duplicates"] += 1
        else:
            counts["staged"] += 1
    return counts
