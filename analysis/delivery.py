"""Keepsake delivery — recipient parsing and an approval-gated send dry-run.

Plan 0003, approach 1 (approval-gated): an email is rendered to disk and handed to the
Gmail MCP as a *draft* that the owner reviews and sends — per Decision D9
(human-in-the-loop, no stored mail credentials). This module holds the reusable,
side-effect-free pieces: parsing the gitignored recipient list and assembling a dry-run
summary that sends nothing. The actual draft creation happens through the Gmail MCP in a
Claude session, not from here.

Roadmap #48: delivery is per *kind* (``EMAIL_KINDS``), not per the weekly note, so the
annual year-in-review digest can reach the family too instead of being rendered and
stranded on disk.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .utils import DATA_DIR

CRON_DIR = DATA_DIR / "cron"
EMAIL_DIR = CRON_DIR / "emails"
RECIPIENTS_PATH = CRON_DIR / "recipients.txt"

DEFAULT_SUBJECT = "From the archive"


@dataclass(frozen=True)
class EmailKind:
    """One deliverable keepsake: how to find its newest render, and how to describe it.

    ``detail_fields`` maps a log-record key to the label the dry run prints it under,
    which is what lets one summary serve every kind instead of hard-coding the weekly
    note's headline and matched article.
    """

    label: str
    pattern: str
    log_name: str
    detail_fields: tuple[tuple[str, str], ...]


# Every kind renders into the same EMAIL_DIR, so each pattern must match only its own
# files. A single `*.html` glob would let the annual digest be drafted as the weekly note.
EMAIL_KINDS: dict[str, EmailKind] = {
    "on-this-day": EmailKind(
        label="On This Day",
        pattern="on_this_day_*.html",
        log_name="on_this_day.jsonl",
        detail_fields=(("headline", "Headline"), ("matched_article", "Matched article")),
    ),
    "year-in-review": EmailKind(
        label="Year in Review",
        pattern="year_in_review_*.html",
        log_name="year_in_review.jsonl",
        detail_fields=(("year", "Year"), ("article_count", "Articles"), ("total_words", "Words")),
    ),
}

DEFAULT_KIND = "on-this-day"


def email_kind(kind: str) -> EmailKind:
    """Look up a kind, refusing an unknown one by name rather than guessing a default."""
    try:
        return EMAIL_KINDS[kind]
    except KeyError:
        known = ", ".join(sorted(EMAIL_KINDS))
        raise ValueError(f"unknown email kind {kind!r}; known kinds: {known}") from None


def log_path_for(kind: str, cron_dir: Path = CRON_DIR) -> Path:
    """The metadata log the given kind appends to, beside the other cron logs."""
    return Path(cron_dir) / email_kind(kind).log_name


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
    log_path: Path | None = None,
    recipients_path: Path = RECIPIENTS_PATH,
    *,
    kind: str = DEFAULT_KIND,
) -> dict | None:
    """Assemble the Gmail-MCP payload for the most recent email of ``kind``.

    Returns {kind, to, subject, html_body, email_file, details} or None if that kind
    has nothing rendered yet. This is the single source the draft helper and the send
    trigger both consume — no second recipient mechanism.
    """
    spec = email_kind(kind)
    if log_path is None:
        log_path = log_path_for(kind)
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
        "details": {label: str(meta.get(field, "")) for field, label in spec.detail_fields},
    }


def format_dry_run(payload: dict) -> str:
    """Render a human-readable summary of what a send *would* do. Sends nothing."""
    spec = email_kind(payload["kind"])
    to = payload.get("to") or []
    lines = [f"=== {spec.label} — DRY RUN (nothing sent) ==="]
    if to:
        lines.append(f"To ({len(to)} recipient{'s' if len(to) != 1 else ''}):")
        lines.extend(f"  - {addr}" for addr in to)
    else:
        lines.append("To: (no recipients configured — see data/cron/recipients.example.txt)")
    lines.append(f"Subject: {payload.get('subject', DEFAULT_SUBJECT)}")
    lines.append(f"File: {payload.get('email_file') or 'N/A'}")
    for label, value in (payload.get("details") or {}).items():
        lines.append(f"{label}: {value or 'N/A'}")
    lines.append(f"Body: {len(payload.get('html_body', ''))} chars of HTML")
    return "\n".join(lines)
