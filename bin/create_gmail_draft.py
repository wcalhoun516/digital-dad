#!/usr/bin/env python3
"""Approval-gated delivery for the latest rendered keepsake email.

Reads the most recent rendered email of a given *kind* + the gitignored recipient list
and prepares it for the Gmail MCP, which the owner reviews and sends — per Decision D9
(email stays a human-reviewed *draft*, no SMTP, no stored credentials). This script never
sends mail itself; the actual draft is created through the Gmail MCP in a Claude
session.

Usage:
    python bin/create_gmail_draft.py                       # the weekly On This Day note
    python bin/create_gmail_draft.py --kind year-in-review  # the annual digest
    python bin/create_gmail_draft.py --dry-run   # summarize what a send would do (sends nothing)
    python bin/create_gmail_draft.py --json       # emit the MCP-ready payload as JSON
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.delivery import (  # noqa: E402
    DEFAULT_KIND,
    EMAIL_KINDS,
    email_kind,
    format_dry_run,
    latest_email_payload,
)

# What to run when a kind has nothing rendered yet.
BUILD_HINT = {"on-this-day": "make on-this-day", "year-in-review": "make year-in-review"}


def main():
    parser = argparse.ArgumentParser(description="Prepare the latest keepsake email for the Gmail MCP")
    parser.add_argument(
        "--kind",
        choices=sorted(EMAIL_KINDS),
        default=DEFAULT_KIND,
        help="Which keepsake to prepare (default: %(default)s)",
    )
    parser.add_argument("--json", action="store_true", help="Output the MCP-ready payload as JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Summarize recipients/subject/details without sending or emitting payload",
    )
    args = parser.parse_args()

    spec = email_kind(args.kind)
    payload = latest_email_payload(kind=args.kind)
    if not payload:
        print(f"No {spec.label} emails found. Run: {BUILD_HINT[args.kind]}")
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
    print(f"File: {payload['email_file']}")
    for label, value in payload["details"].items():
        print(f"{label}: {value or 'N/A'}")
    print("\nTo create a Gmail draft, use Claude Code with the Gmail MCP:")
    print(f"  'Create a Gmail draft with the latest {spec.label} email'")


if __name__ == "__main__":
    main()
