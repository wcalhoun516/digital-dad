# Daily log

Working memory for the daily product-dev agent (`scripts/daily_routine_prompt.md`).

---

## How to add ideas

You have three ways to influence what the agent builds, in **priority order** (the agent
prefers earlier ones):

1. **Pre-baked plan (hot path, highest priority).** Drop a `NNNN-slug.md` implementation plan
   into [`plans/ready/`](plans/ready/). The agent executes the *oldest* one first via the
   `superpowers:executing-plans` skill, then moves it to `plans/done/`. Best for work you've
   already thought through.
2. **User pin (middle priority).** Add a line under `## User pins` below. The agent works the
   **first unchecked `[ ]`** pin. Best for "just do this next" without writing a full plan.
3. **Roadmap (cold path, lowest priority).** Add/raise an item in
   [`roadmap.md`](roadmap.md). When there's no plan and no pin, the agent picks the
   least-recently-worked category and pulls the highest-priority item from it.

The agent opens **one small draft PR per day**, never merges, never pushes to `main`. Review
the PR during the day; merge it yourself if you're happy.

---

## User pins

Add tasks here as `- [ ] description`. The agent takes the first unchecked one. Check it off
(`- [x]`) once its PR merges, or delete it.

- [ ] (no pins yet)

---

## Run history

Newest on top. The agent appends one entry per run. It tallies the `Category:` of the last 7
entries to decide the least-recently-worked category for cold-path selection.

Format:
```
### <YYYY-MM-DD> — <Category> — <Status>
- PR: <link or #num> (or "skipped" / "none")
- Source: <plan:ready/NNNN | pin | roadmap:#N | resume>
- Summary: <one line>
```

<!-- entries below -->

### 2026-06-17 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/23
- Source: plan:ready/0008
- Summary: Plan 0008, **de-risks step 26c** (smallest viable QLoRA run) with a pure, offline
  **training-data preflight** — `training/finetune_preflight.py` + `make finetune-preflight`.
  Hot-path pick (0008 still the only plan in `ready/`). The remaining 0008 steps all need
  owner-interactive compute or the sibling conductor repo (26c real training on the M4; 26d/26f
  live T3 *paid* judge; 26e edits `models.yaml` outside this repo), so — matching prior runs — I
  shipped the **verifiable deterministic slice**: a check that validates 26a's
  `data/training/{train,heldout}.jsonl` against the run's `QLoRAConfig` **before** anyone burns
  M4 time. Three checks: **chat-shape integrity** (non-empty system/user/assistant), **split
  disjointness** (no body leaks train→heldout, keyed on assistant-content hash so a reworded
  prompt can't hide it), and **sequence-length budget** (est tokens vs `max_seq_len`, ~4
  chars/token, no model download). Report-only (exit 0, never reddens `make verify`); `--strict`
  gates, `--json` for machines, `--max-seq-len`/`--base` for what-ifs. **Real finding it surfaces:**
  shape + disjointness PASS, but **100% of 172 records exceed the default `max_seq_len=1024`**
  (est tokens median ~3,041, max ~5,319) because the assistant turn is a full article body — the
  26c run as configured would silently train on truncated stubs. §8.5 deepen made it actionable:
  the report now suggests a `max_seq_len` (smallest pow2 covering ~95%: **≈8192**, P95 ≈4,354) or
  chunking. TDD'd: 26 new tests (`tests/test_finetune_preflight.py`). `make verify` green (ruff +
  **261 tests** + dashboard build). Plan 0008 stays in `plans/ready/` (26c training + 26d/26f live
  + 26e conductor remain — all owner-interactive). No data artifacts committed (§11).

### 2026-06-16 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/21
- Source: plan:ready/0008
- Summary: Plan 0008 step **26d — voice-fidelity eval harness, first unattended-friendly slice.**
  Hot-path pick (0008 still the only plan in `ready/`). 26d's live judge (T3) + the `finetuned`
  candidate both need owner-interactive compute (the 26c adapter isn't trained yet), so — like
  26b/26c — I shipped the **verifiable deterministic half**: new `analysis/voice_eval.py`, a blind
  A/B/C ranking harness modeled on `analysis/rag_eval.py`'s injected-seam pattern. For each
  held-out prompt it anonymizes candidate passages (`real`/`rag`/`finetuned`) to labels A/B/C with
  a **seeded, reproducible** shuffle, has a judge rank them by Calhoun-voice, then un-blinds and
  aggregates **win-rate / avg-rank / head-to-head** (`finetuned_over_rag`) per source. TDD'd: 25
  tests (`blind_candidates`, tolerant `parse_ranking`, `unblind_ranking`, `evaluate`, `aggregate`,
  `render_markdown`, `write_report`). Live `judge` seam (conductor T3) + `make voice-eval` CLI gated
  on conductor reachability (paid-call safety, mirrors rag-eval); plus a trials-input template
  (`eval/voice_trials.example.json`) and a README section. `make verify` green (204 passed +
  dashboard build). **Deliberately self-contained off `main`:** I *deferred* folding in
  `style_metrics` (which lives in #20's still-unmerged `training/finetune_config.py`) so this PR has
  **no dependency on unmerged code** — noted as the next seam for a future slice. **Not done in 26d:**
  the live A/B run itself (needs the trained adapter + the real `finetuned`/`real`/`rag` candidates,
  owner-interactive). Plan 0008 stays in `plans/ready/` (26c training + 26d live run remain; 26e–26f
  after). NB: 26b (#19) and 26c (#20) are still unmerged ahead of this.

### 2026-06-13 — scraper — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/18
- Source: roadmap:#8
- Summary: Roadmap **#8 — manifest integrity checker** (`scraper/manifest_check.py` + `make
  manifest-check`). **Cold-path pick:** the hot-path queue is stalled — plans 0007/0008 are
  done-pending-merge on PRs #16/#17, and 0008's next step (26b baseline capture) is blocked on
  those merges *and* an owner-gated paid eval, so nothing in `plans/ready/` is runnable unattended
  without duplicating PRs #16/#17. Picked the least-recently-worked category (last 7 runs:
  dashboard×4, training/analysis/family×1; scraper/docs/infra never appeared) and chose scraper #8
  because it directly addresses PR #17's surprising find. Pure `audit_manifest` (TDD'd offline)
  detects duplicate slug/url/content_hash, missing content_hash, manifest↔disk drift
  (missing/orphaned files), and total_articles count drift; `run()` adds `--json` (machine output)
  and `--strict` (exit 1 on issues, for a future CI/pre-commit gate — #5) while staying report-only
  (exit 0) by default so it never turns `make verify` red. 25 new tests (145 total); `make verify`
  green. **On the real corpus it confirms PR #17 exactly: 23 duplicate slugs** — root cause is the
  scraper de-duping manifest entries by **URL not slug** (`scraper/__main__.py`), so an article
  rediscovered under a variant URL appends a second entry. Also surfaced **1 duplicate
  content_hash** (the `george-calhoun` author-listing page scraped twice) and **168 entries
  missing `content_hash`** (scraped before that field existed); no missing/orphaned files.
  Documented findings + root cause in a new `scraper/README.md`. The checker only *reports* — the
  manifest de-dup + content_hash backfill it exposes are separate owner-reviewed follow-ups.

### 2026-06-10 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/15
- Source: plan:ready/0006
- Summary: Plan 0006 step 4 (don't regress desktop; verify both breakpoints) — the live
  phone-width browser pass that steps 1–3 each deferred as "no preview tooling." Playwright +
  Chromium turned out to be available in `.venv`, so added `viz/verify_responsive.py` (run via
  `make verify-responsive`): a headless-Chromium harness that renders the *built* index.html at
  desktop (1280×900) and phone (375×812) and asserts no horizontal overflow, a clean JS console,
  the corpus table staying a real table on desktop while reflowing to labelled cards on a phone,
  and step-2's resize-redraw surviving a live desktop→phone transition. **10/10 checks passed**;
  screenshots confirm the card reflow. Pure pass/fail report logic TDD'd (3 tests, 120 total);
  harness kept out of `make verify` (CI has no browser; it SKIPs cleanly when Chromium is absent).
  This **completes plan 0006** — moved to `docs/plans/done/`. The whole `plans/ready/` queue now
  has 0007 (RAG faithfulness eval) as the next hot-path item.

### 2026-06-09 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/14
- Source: plan:ready/0006
- Summary: Plan 0006 step 3 — the Raw Corpus table (the one remaining wide
  `<table>`; Track Record already renders as cards) now reflows into labelled
  cards at ≤480px instead of forcing a horizontal scroll. Header visually hidden,
  cells block-level, each field name drawn from a new `data-label` via
  `td::before`; long titles wrap, and empty theme/tags cells are hidden
  (`td:empty`) so a card never shows an orphan label. Gives a 3-step ladder:
  desktop table → ≤768px scroll → ≤480px cards. TDD'd with 5 new tests
  (`tests/test_dashboard_responsive.py`, now 117 total). Verified via `make verify`
  (ruff + 117 tests + dashboard build) and confirmed the built index.html carries
  the change. **Live phone-width browser pass not run** (headless, no preview
  tooling) — reviewer should eyeball ~375px Raw Corpus before merging. Plan 0006
  left in `ready/` (step 4 — dual-breakpoint device verification — remains).

### 2026-06-08 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/13
- Source: plan:ready/0006
- Summary: Plan 0006 step 2 — D3 charts re-render on viewport change. Added a debounced
  window `resize` handler that re-renders the active chart tab so the pixel-sized charts
  (theme map, timeline) re-measure their container after a resize / phone rotation. Made
  `renderThemeMap`/`renderTimeline` idempotent (clear SVG + legend; sentiment toggle uses
  `onclick =` not `addEventListener`) so a redraw can't stack duplicate nodes/axes/listeners.
  Redraw is limited to a `RESIZE_REDRAW_TABS` set (themes, timeline) so interactive tabs
  (Ask Dad, Corpus) keep in-flight state; radar/linguistic already scale via viewBox (D13).
  TDD'd with 8 new structural tests (`tests/test_dashboard_responsive.py`); recorded the
  approach as ADR D14. Verified via `make verify` (ruff + 112 tests + dashboard build).
  **Live phone-width browser pass not run** (headless, no preview tooling) — reviewer should
  rotate/resize a real ~375px viewport before merging. Plan 0006 left in `ready/` (steps 3–4
  — table reflow + dual-breakpoint device verification — remain).

### 2026-06-07 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/9
- Source: plan:ready/0006
- Summary: Mobile-responsive dashboard, first slice (plan 0006 step 1). Added the dashboard's
  first `@media` layer to `dashboard/template.html`: scrollable 9-tab nav, fluid header/padding
  + scaled type at 768/480px, single-column chart grid, horizontally-scrollable wide tables.
  Deepened by giving the fixed 400×400 radar a `viewBox` so it scales on phones, and recorded
  the CSS-foundation-first approach (D3 resize deferred to step 2) as ADR D13. TDD'd with 6
  tests (`tests/test_dashboard_responsive.py`); verified via `make verify` (lint + 71 tests +
  dashboard build). **Live phone-width browser pass not run** (headless, no preview tooling) —
  reviewer should eyeball ~375px before merging. Plan left in `ready/` (only step 1 done).

### 2026-06-04 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/6
- Source: plan:ready/0004
- Summary: Track Record human-adjudication layer (plan 0004 steps 2-4). New
  `analysis/adjudicate.py` — status precedence (human > llm > status), `apply_adjudication`
  writeback, resumable `python -m analysis.adjudicate` CLI + `make adjudicate`, TDD'd with 24
  tests. Dashboard now lets a family ruling win (family-confirmed marker). Deepened with
  confidence calibration (`calibration_report` + `conviction_boards`, `--report`, roadmap #12).
  Plan 0004 left in `ready/` — step 1 (web-search verdict backfill) is a future run.

### 2026-06-03 — family — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/5
- Source: plan:ready/0003
- Summary: On This Day approval-gated delivery (approach 1, per D9). New
  `analysis/delivery.py` (recipient parsing + payload + dry-run, TDD'd with 14 tests),
  refactored `bin/create_gmail_draft.py` onto it with `--dry-run`, added
  `make send-on-this-day` owner approval gate + README docs. Plan moved to `plans/done/`.

### 2026-06-02 — infra — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/3
- Source: plan:ready/0002
- Summary: Added `.github/workflows/verify.yml` (runs `make lint`/`make test` on PRs + pushes
  to main, with a guard that fails loudly if 0001's make targets are missing) and a CI status
  badge in `README.md`. Plan moved to `plans/done/`.

### 2026-05-30 — infra — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/1
- Source: plan:ready/0001
- Summary: Added pytest + ruff dev deps, `tests/` scaffold with 27 characterization tests
  (scraper/analysis utils + corpus-fingerprint), and `make test/lint/fmt/verify`. Plan moved
  to `plans/done/`.
