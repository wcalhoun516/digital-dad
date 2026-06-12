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

### 2026-06-12 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/17
- Source: plan:ready/0008
- Summary: Plan 0008 step 1 (**26a — dataset builder**), the first slice toward "Geo LLM"
  (roadmap #26). Extended `training/prepare.py` to emit `data/training/{train,heldout}.jsonl`
  from the quality-filtered instruct records, with a **deterministic** partition (stable slug
  hash) and a **leakage-free** contract against the #25 RAG eval: articles a question in
  `eval/questions.json` is grounded in are reserved out of *both* splits, so the future voice
  fine-tune can't memorize the faithfulness eval's answers. Refactored the inline instruct
  shaping into a tested `build_instruct_record`; added `eval_grounded_slugs` (normalized,
  punctuation-robust title→question matching) and `split_articles`. TDD'd with 12 new tests on
  fixtures (132 total); `make verify` green (lint + tests + dashboard). Ran end-to-end on the
  real corpus: 172 unique quality articles → train (138) + heldout (34); demonstrated the
  exclusion against the real plan-0007 questions (5 eval-grounded articles matched, 0 leak into
  either split). Outputs are gitignored (extended `.gitignore` + `make clean`); documented in a
  new `training/README.md`. **Sequencing note:** `eval/questions.json` lives on PR #16 (plan
  0007) and isn't on `main` yet, so the builder reads it when present and warns+skips the
  exclusion when absent — the pure logic is fixture-tested independently. **Surprising find:**
  the manifest has 23 duplicate slugs (~12% of 196 entries) — same articles re-discovered via
  different scraper tiers; the split de-dups by slug, but a human may want to look at why the
  manifest carries dupes. Plan 0008 left in `ready/` (steps 26b–26f remain).

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
