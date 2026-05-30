#!/usr/bin/env python3
"""Create a Gmail draft from the latest On This Day email.

This script reads the most recent On This Day email from data/cron/emails/
and prints instructions for creating a Gmail draft. When used with the
Gmail MCP in Claude Code, the draft can be created automatically.

Usage:
    python bin/create_gmail_draft.py          # show latest email info
    python bin/create_gmail_draft.py --json   # output JSON for programmatic use
"""

import argparse
import json
import sys
from pathlib import Path

EMAIL_DIR = Path(__file__).resolve().parent.parent / "data" / "cron" / "emails"
LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "cron" / "on_this_day.jsonl"
RECIPIENTS_PATH = Path(__file__).resolve().parent.parent / "data" / "cron" / "recipients.txt"


def read_recipients():
    """Read the recipient list (one address per line; '#' lines ignored).

    Falls back to an empty list if the file is missing — copy
    data/cron/recipients.example.txt to recipients.txt to configure.
    """
    if not RECIPIENTS_PATH.exists():
        return []
    recipients = []
    for line in RECIPIENTS_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            recipients.append(line)
    return recipients


def get_latest():
    """Get the latest On This Day email and metadata."""
    if not EMAIL_DIR.exists():
        return None, None

    emails = sorted(EMAIL_DIR.glob("on_this_day_*.html"), reverse=True)
    if not emails:
        return None, None

    html = emails[0].read_text()

    # Get metadata from log
    meta = None
    if LOG_PATH.exists():
        for line in reversed(LOG_PATH.read_text().splitlines()):
            try:
                meta = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return html, meta


def main():
    parser = argparse.ArgumentParser(description="Show latest On This Day email")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    html, meta = get_latest()
    if not html:
        print("No On This Day emails found. Run: make on-this-day")
        sys.exit(1)

    recipients = read_recipients()

    if args.json:
        print(json.dumps({
            "to": recipients,
            "subject": meta.get("subject", "From the archive") if meta else "From the archive",
            "html_body": html,
            "headline": meta.get("headline", "") if meta else "",
            "matched_article": meta.get("matched_article", "") if meta else "",
        }))
    else:
        subject = meta.get("subject", "From the archive") if meta else "From the archive"
        print(f"To: {', '.join(recipients) if recipients else '(none configured — see data/cron/recipients.example.txt)'}")
        print(f"Subject: {subject}")
        print(f"Headline: {meta.get('headline', 'N/A') if meta else 'N/A'}")
        print(f"Matched: {meta.get('matched_article', 'N/A') if meta else 'N/A'}")
        print(f"\nTo create a Gmail draft, use Claude Code with the Gmail MCP:")
        print(f"  'Create a Gmail draft with the latest On This Day email'")


if __name__ == "__main__":
    main()
