# docs/ — index & read order

This directory is the durable context for any Claude (or human) session working on
`digital-dad`. Start here.

## Read order

1. **[`../CLAUDE.md`](../CLAUDE.md)** — 30-second orientation, key commands, what's built.
2. **[`architecture.md`](architecture.md)** — the repo map, data flow, and the conductor
   LLM abstraction. Read this before touching any module.
3. **[`goals.md`](goals.md)** — the north star. Why this project exists and what "good"
   looks like.
4. **[`decisions.md`](decisions.md)** — ADR-style log of the non-obvious choices and their
   rationale. Check here before reversing something that looks odd.
5. **[`roadmap.md`](roadmap.md)** — the forward backlog (28 ideas, grouped & prioritized).
   This is the **source of truth** for what to build next. Human-curated; the daily agent
   reads it but never edits it.

## Contributor guides

- **[`conductor-contract.md`](conductor-contract.md)** — the formal LLM contract: chat +
  embeddings call shapes, tiers/routing, `model_used`, error modes & the conductor health
  check. The reference behind `architecture.md` §3.
- **[`runbooks/adding-an-analysis-module.md`](runbooks/adding-an-analysis-module.md)** —
  step-by-step for adding a module to the `analysis/` pipeline (shape, `__main__` wiring,
  fingerprint-skip, dashboard injection, tests).

## Operational

- **[`daily-log.md`](daily-log.md)** — the daily product-dev agent's working memory:
  how to add ideas, your pinned tasks (`## User pins`), and the run history.
- **[`changelog.md`](changelog.md)** — human-curated record of notable shipped changes.
- **[`plans/ready/`](plans/ready/)** — pre-baked implementation plans the daily agent
  executes first (the "hot path"). Drop a plan here to make it tomorrow's top priority.
- **[`plans/done/`](plans/done/)** — completed plans, moved here after execution.

## Map of the repo (pointers)

| Area | Where | Notes |
|------|-------|-------|
| Scraper | `scraper/` | 3-tier discovery + extraction; see architecture.md |
| Analysis | `analysis/` | linguistic, themes, entities, psychoprofile, semantic_search, predictions |
| Dashboard | `dashboard/template.html`, `viz/build_dashboard.py` | client-side D3, template injection |
| Training | `training/prepare.py`, `notebooks/` | fine-tune data prep + QLoRA notebook |
| Data | `data/` | `raw/`, `analysis/`, `manifest.json`, `cron/` |
| Weekly cron | `bin/` | `com.calhoun.digitaldad-weekly` (Sun 03:00) |
| Daily agent | `scripts/` | `com.calhoun.digitaldad-daily` (01:00) + prompt + launchd |
