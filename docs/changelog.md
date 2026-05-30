# Changelog

Human-curated record of notable shipped changes. **The daily product-dev agent never edits
this file** — maintainers update it when work merges. Newest on top.

## 2026-05-29

- Added `docs/` (architecture, goals, decisions, roadmap, daily-log) and root `CLAUDE.md` as
  durable session context.
- Stood up the **daily product-dev agent**: `scripts/daily_routine_prompt.md` playbook +
  launchd job `com.calhoun.digitaldad-daily` (01:00 daily, opus-4.8/high) producing one
  reviewable draft PR per day. Never merges, never pushes to `main`.

## Earlier

- Initial project: complete scraper, analysis, dashboard, and training pipeline.
- Shipped Ask Dad (RAG chat), Track Record (predictions audit), and On This Day (weekly email).
