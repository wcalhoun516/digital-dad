# CLAUDE.md — primary context for Claude sessions

> **digital-dad** is an intellectual archive of Dr. George Calhoun's Forbes columns:
> scrape his articles, analyze them, and make the corpus explorable and alive for his
> family. Built by his son.

If you are a Claude session starting work here, **read [`docs/INDEX.md`](docs/INDEX.md) first** —
it is the curated entry point and tells you what to read next.

## The 30-second orientation

- **Pipeline:** `scrape → analyze → synthesize → dashboard/email`. One Makefile drives it.
- **Stack:** Python ≥3.12 in `.venv`, Make targets, vanilla-JS + D3 dashboard (no build
  step, no framework), launchd for scheduling. macOS, repo on an **external volume**
  (`/Volumes/FamilyWorkDrive`).
- **LLM access:** everything routes through the **conductor**, a local OpenAI-compatible
  server at `http://127.0.0.1:8080/v1` (sibling repo `local-llm-conductor`). Tiers:
  T1 `phi3:mini` (cheap rewrites), T2 local reasoning model (free), T3 OpenRouter (paid).
  No API keys live in this repo.
- **Data:** raw articles in `data/raw/*.json` (gitignored — licensing), analysis outputs
  in `data/analysis/*.json`, manifest at `data/manifest.json`.

## Key commands

```bash
make scrape         # discover + extract Forbes articles (Playwright→sitemap→Wayback)
make analyze        # run the analysis pipeline (fingerprint-skips unchanged work)
make dashboard      # inject analysis JSON into dashboard/template.html → index.html
make serve          # build dashboard + serve on :8000
make on-this-day    # generate the weekly "On This Day" email
make all            # scrape + analyze + training + dashboard
```

There is currently **no `make test` / `make lint`** — adding them is roadmap item #1–3.
Until then, verify Python edits with `.venv/bin/python -m py_compile <file>` and dashboard
edits with `make dashboard`.

## What's already built (don't rebuild)

All three "headline" features are complete and shipping:
- **Ask Dad** — RAG chat in the dashboard (`dashboard/template.html`, semantic_search index).
- **Track Record** — falsifiable-prediction audit (`analysis/predictions.py` + dashboard tab).
- **On This Day** — weekly news→archive email (`analysis/on_this_day.py` + Gmail-MCP draft).

## Automation

- **Weekly** (`bin/`): `com.calhoun.digitaldad-weekly`, Sun 03:00 — refreshes the corpus
  and dashboard. **Do not modify this from automated runs.**
- **Daily product-dev agent** (`scripts/`): `com.calhoun.digitaldad-daily`, 01:00 — runs
  Claude headlessly to produce one small reviewable **draft** PR per day. Its playbook is
  [`scripts/daily_routine_prompt.md`](scripts/daily_routine_prompt.md). It never merges
  and never pushes to `main`.

See [`docs/architecture.md`](docs/architecture.md) for the full map and
[`docs/decisions.md`](docs/decisions.md) for *why* things are the way they are.
