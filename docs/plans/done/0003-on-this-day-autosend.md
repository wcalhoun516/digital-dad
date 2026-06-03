# Plan 0003 — On This Day: real delivery to the family

## Goal

Make the weekly "On This Day" email actually **reach the family** on a configurable
recipient list, with a human-approval gate so nothing goes out unreviewed. Today
`analysis/on_this_day.py` only renders HTML to disk and `bin/create_gmail_draft.py` hands it
to the Gmail MCP as a *draft* — a person still has to manually send each week. This closes
that gap while keeping a person in the loop.

## Context

- Existing pieces to reuse: `analysis/on_this_day.py` (generates the email + logs to
  `data/cron/on_this_day.jsonl`), `bin/create_gmail_draft.py` (MCP draft helper),
  `bin/weekly_run.sh` (the Sunday cron that already calls `make on-this-day`).
- **Recipient list already exists:** `data/cron/recipients.txt` (gitignored; one address
  per line, `#` comments ignored; committed example at `recipients.example.txt`).
  `bin/create_gmail_draft.py` already reads it via `read_recipients()` and emits a `to`
  field. It currently holds the owner's address only — the owner adds family members over
  time by editing that file. Reuse this; do not invent a second recipient mechanism.
- **Owner's delivery preference:** Gmail draft via the Gmail MCP, addressed to the recipient
  list, which the owner reviews and sends — *not* unattended SMTP. Honor this unless the
  owner explicitly asks for automatic SMTP later.
- **Decision D9** (see `docs/decisions.md`): email is intentionally a Gmail-MCP *draft*, not
  SMTP — to keep a human in the loop and avoid storing mail credentials. This plan should
  *extend* that posture, not silently bypass it.
- **Constraint:** no credentials may be committed; `.env` is gitignored and off-limits to the
  agent. Any SMTP path must read secrets from the environment / the conductor's own `.env`.

## Open design decision — resolve with `superpowers:brainstorming` first

Two viable approaches; pick one and record the choice in the PR body:
1. **Approval-gated send (recommended default, safest):** keep generating the draft, but add
   a configurable recipient list (`data/cron/recipients.txt`, gitignored) and a one-step
   "approve & send" path the owner triggers (e.g. a `make send-on-this-day` that sends the
   most recent approved email). Weekly cron generates + notifies the owner; it does **not**
   auto-send. Preserves D9's human-in-the-loop.
2. **SMTP auto-send with override window:** send automatically via SMTP (app password from
   env) to the recipient list, but only after a configurable hold/override window during
   which the owner can cancel. More automated, more risk; requires storing an app password
   outside the repo.

Default to (1) unless the owner has said they want true automation.

## Steps (sketch — refine in the chosen approach)

1. Brainstorm + choose the approach; write the decision into the PR and add an ADR line to
   note for `docs/decisions.md` (don't edit decisions.md from the agent — propose it in the PR).
2. Add a recipient-list config (gitignored; ship a `recipients.example.txt`).
3. Implement the send path (Gmail MCP approve-send, or SMTP) reading recipients + secrets
   from outside the repo. Add a `--dry-run` that prints what *would* send.
4. Add a clear owner-facing trigger (`make` target or a `bin/` script) and document it.
5. Wire an *opt-in* hook into `bin/weekly_run.sh` only if approach (2) is chosen and approved.

## Verification

- `--dry-run` shows the correct recipients + subject + matched article, sends nothing.
- A real send to a single test address (the owner's own email) arrives correctly rendered.
- TDD the recipient-parsing + dry-run logic (`superpowers:test-driven-development`).
- `superpowers:verification-before-completion` before flipping ready; paste the dry-run output.

## Out of scope

- Year-in-review digest (#23), anthology PDF (#24), editorial re-ranking of the matched
  article (the cosine match stays as-is for now).
