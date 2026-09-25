"""On This Day delivery — recipient parsing and an approval-gated send dry-run.

Plan 0003, approach 1 (approval-gated): the weekly email is rendered to disk and
handed to the Gmail MCP as a *draft* that the owner reviews and sends — per
Decision D9 (human-in-the-loop, no stored mail credentials). This module holds the
reusable, side-effect-free pieces: parsing the gitignored recipient list and
assembling a dry-run summary that sends nothing. The actual draft creation happens
through the Gmail MCP in a Claude session, not from here.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .utils import DATA_DIR

CRON_DIR = DATA_DIR / "cron"
EMAIL_DIR = CRON_DIR / "emails"
LOG_PATH = CRON_DIR / "on_this_day.jsonl"
RECIPIENTS_PATH = CRON_DIR / "recipients.txt"

DEFAULT_SUBJECT = "From the archive"


@dataclass(frozen=True)
class EmailKind:
    """One deliverable keepsake: how to find its newest render, and how to describe it."""

    label: str
    pattern: str


# Every kind renders into the same EMAIL_DIR, so each pattern must match only its own
# files. A single `*.html` glob would let the annual digest be drafted as the weekly note.
EMAIL_KINDS: dict[str, EmailKind] = {
    "on-this-day": EmailKind(label="On This Day", pattern="on_this_day_*.html"),
    "year-in-review": EmailKind(label="Year in Review", pattern="year_in_review_*.html"),
}

DEFAULT_KIND = "on-this-day"


def _looks_like_email(value: str) -> bool:
    """Cheap structural check: exactly one '@' with non-empty local and domain."""
    parts = value.split("@")
    return len(parts) == 2 and all(parts)


def parse_recipients(text: str) -> list[str]:
    """Parse a recipient list: one address per line.

    Blank lines and '#' comments are ignored, whitespace is stripped, entries are
    deduped preserving first-seen order, and anything that isn't structurally an
    email address is dropped (so a stray note in the file can't become a 'to').
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _looks_like_email(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def read_recipients(path: Path = RECIPIENTS_PATH) -> list[str]:
    """Read + parse the recipient file; empty list if it doesn't exist."""
    path = Path(path)
    if not path.exists():
        return []
    return parse_recipients(path.read_text())


def _latest_meta(log_path: Path) -> dict | None:
    """Return the most recent valid JSON record from the On This Day log."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def latest_email_payload(
    email_dir: Path = EMAIL_DIR,
    log_path: Path = LOG_PATH,
    recipients_path: Path = RECIPIENTS_PATH,
    *,
    kind: str = DEFAULT_KIND,
) -> dict | None:
    """Assemble the Gmail-MCP payload for the most recent email of ``kind``.

    Returns {kind, to, subject, html_body, email_file, headline, matched_article} or
    None if that kind has nothing rendered yet. This is the single source the draft
    helper and the send trigger both consume — no second recipient mechanism.
    """
    spec = EMAIL_KINDS[kind]
    email_dir = Path(email_dir)
    if not email_dir.exists():
        return None
    emails = sorted(email_dir.glob(spec.pattern), reverse=True)
    if not emails:
        return None

    html = emails[0].read_text()
    meta = _latest_meta(log_path) or {}
    return {
        "kind": kind,
        "to": read_recipients(recipients_path),
        "subject": meta.get("subject", DEFAULT_SUBJECT),
        "html_body": html,
        "email_file": emails[0].name,
        "headline": meta.get("headline", ""),
        "matched_article": meta.get("matched_article", ""),
    }


def format_dry_run(payload: dict) -> str:
    """Render a human-readable summary of what a send *would* do. Sends nothing."""
    to = payload.get("to") or []
    lines = ["=== On This Day — DRY RUN (nothing sent) ==="]
    if to:
        lines.append(f"To ({len(to)} recipient{'s' if len(to) != 1 else ''}):")
        lines.extend(f"  - {addr}" for addr in to)
    else:
        lines.append("To: (no recipients configured — see data/cron/recipients.example.txt)")
    lines.append(f"Subject: {payload.get('subject', DEFAULT_SUBJECT)}")
    lines.append(f"Headline: {payload.get('headline') or 'N/A'}")
    lines.append(f"Matched article: {payload.get('matched_article') or 'N/A'}")
    lines.append(f"Body: {len(payload.get('html_body', ''))} chars of HTML")
    return "\n".join(lines)
