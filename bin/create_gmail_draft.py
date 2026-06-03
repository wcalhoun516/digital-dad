#!/usr/bin/env python3
"""Approval-gated delivery for the latest On This Day email.

Reads the most recent rendered email + the gitignored recipient list and prepares
it for the Gmail MCP, which the owner reviews and sends — per Decision D9 (email
stays a human-reviewed *draft*, no SMTP, no stored credentials). This script never
sends mail itself; the actual draft is created through the Gmail MCP in a Claude
session.

Usage:
    python bin/create_gmail_draft.py             # show recipients/subject + MCP instruction
    python bin/create_gmail_draft.py --dry-run   # summarize what a send would do (sends nothing)
    python bin/create_gmail_draft.py --json       # emit the MCP-ready payload as JSON
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.delivery import format_dry_run, latest_email_payload  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Prepare the latest On This Day email for the Gmail MCP")
    parser.add_argument("--json", action="store_true", help="Output the MCP-ready payload as JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Summarize recipients/subject/article without sending or emitting payload",
    )
    args = parser.parse_args()

    payload = latest_email_payload()
    if not payload:
        print("No On This Day emails found. Run: make on-this-day")
        sys.exit(1)

    if args.dry_run:
        print(format_dry_run(payload))
        return

    if args.json:
        print(json.dumps(payload))
        return

    recipients = payload["to"]
    print(f"To: {', '.join(recipients) if recipients else '(none configured — see data/cron/recipients.example.txt)'}")
    print(f"Subject: {payload['subject']}")
    print(f"Headline: {payload['headline'] or 'N/A'}")
    print(f"Matched: {payload['matched_article'] or 'N/A'}")
    print("\nTo create a Gmail draft, use Claude Code with the Gmail MCP:")
    print("  'Create a Gmail draft with the latest On This Day email'")


if __name__ == "__main__":
    main()
