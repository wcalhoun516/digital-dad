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

### 2026-07-17 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/53
- Source: roadmap:#17
- Summary: Roadmap **#17 (P2·M·analysis)** deferred-viz slice — the **"stance over time" dashboard
  tab**. The `entity_stance.py` builder shipped in #50 emitting the committed, text-free
  `entity_stance.json` and *explicitly deferred* its dashboard viz; this builds it — the exact
  analog of open PR #51 (network viz on #14's builder). New **Stance** tab: a D3 **multi-line**
  chart of each subject's yearly `mean_stance` trajectory (zero baseline, per-point hover tooltip,
  click-to-isolate legend) + the builder's warming/cooling trend boards. Wired like Reading Room:
  `/*__ENTITY_STANCE_DATA__*/` placeholder + empty-graph default in `build_dashboard.py`, a
  `renderStance()` dispatched from `renderTab`, added to `RESIZE_REDRAW_TABS`, empty-stub → a
  `make entity-stance` prompt. **Fully offline/unattended-safe** (reads committed text-free JSON;
  no conductor/network/LLM); builds only on **merged `main`** — no dependency on the unmerged
  #51/#52. **Regression caught + fixed in the browser pass:** adding a 12th nav button pushed the
  non-wrapping desktop nav to 1325px (a 45px horizontal scroll) — added `flex-wrap: wrap` to the
  base `nav` rule (no-op ≤11 tabs; wraps the overflow row) + a structural guard test. TDD'd: +10
  tests (`tests/test_dashboard_stance.py`). **Verification:** `make verify` green (**608 passed**,
  up from 598; ruff clean; dashboard builds); headless-Chromium pass on the built `index.html` —
  Stance tab desktop 1280×900 & phone 375×812: 8 paths / 34 circles rendered, tooltip shows on
  hover, **0 console errors, no horizontal overflow at either width**. **Task pivot note:** branch
  is slugged `year-in-review` but roadmap #23 is already shipped (`analysis/year_in_review.py` on
  `main`) — my §1 read a stale pre-fetch `main`; re-ran §5b against real `main` and pivoted to #17.
  **Cold-path pick:** hot-path queue drained (0008 remainder owner-interactive), no pins, roadmap
  nearly exhausted — #14-viz/#15 already claimed by #51/#52, leaving #17's deferred viz the
  remaining genuinely-unstarted, fully-offline slice (strong family payoff). **Deferred (inherited
  from #17 builder):** entity **alias fragmentation** ("Fed" / "the Federal Reserve" are separate
  lines). **Backlog:** 2 open `daily/*` PRs (#51/#52) before this run — under 5.

### 2026-07-13 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/50
- Source: roadmap:#17
- Summary: Roadmap **#17 (P2·M·analysis)** — **per-entity stance over time** (his evolving view of the
  Fed, Bitcoin, the ECB…), first slice: the pure/offline **builder** (dashboard viz deferred). New
  `analysis/entity_stance.py` mirrors `entity_graph.py` (#14): joins `entities.json`'s `per_article`
  lists to the corpus bodies and emits `entity_stance.json` — per entity a **yearly stance
  trajectory** (mean tone of the sentences that name it, per year) + `overall_stance` +
  warming/cooling **trend boards**. **Key env constraint:** nltk/VADER is absent here (all
  `linguistics.json` sentiment is `{}`), so stance is a **transparent heuristic**, not a model — a
  small curated polarity lexicon scored per sentence (`sentence_polarity`, positive−negative with a
  light 3-token **negation flip**); honest proxy for *tone trends*, not ground-truth sentiment. Reuses
  `entity_graph`'s `article_entities`/`entity_id`/exclude set; sums are accumulated at the **sentence
  level** so yearly/overall means are exact (not means-of-means). `run()` + `python -m
  analysis.entity_stance` CLI (`--dry-run`/`--top`/`--min-articles`/`--min-mentions`/`--threshold`/
  `--exclude`/`--no-exclude`) + `make entity-stance` + architecture note. **§8.5 deepen:** the smoke
  run surfaced Forbes image-credit boilerplate ("Photo") as the top warming entity, so added a
  stance-scoped `_EXTRA_EXCLUDE` (photo/photographer/illustration/image) on top of the shared byline
  set — kept **stance-local** so `entity_graph`'s committed artifact is untouched; plus negation-window
  boundary + sentence-weighting edge tests. **TDD'd:** +22 tests (`tests/test_entity_stance.py`).
  **Licensing:** artifact is **text-free** (names/years/scores only) → committable like
  `entity_graph.json` (contrast the gitignored `calhoun_isms.json`). **Verification:** `make verify`
  green (**565 passed**, up from 543; ruff clean; dashboard builds); real-corpus smoke (`--top 6
  --min-articles 5`): 199 articles → genuine trends (Covid warming, Treasury cooling, "Photo" noise
  gone), 7 KB valid JSON. **Known limitation (documented, deferred like #14):** entity alias
  fragmentation — "Fed" / "the Federal Reserve" / "The Federal Reserve" score as separate entities;
  alias-merging + the dashboard "stance over time" viz are future slices. **Cold-path pick:**
  `plans/ready/` holds only 0008 (26c/26d/26e/26f owner-interactive/paid/compute/sibling-repo — not
  unattended-safe); no user pins. PRs #49 (07-12 analysis) and #48 (07-11 ops) are both
  ready-for-review-but-unmerged, so §3 didn't resume either. Rotation (last worked by category):
  analysis 07-12, ops 07-11, scraper 07-08, infra 07-07, dashboard 07-05, family 07-04 — training
  (06-20)/docs (06-25) drained or compute-heavy (#26/#27); family/dashboard drained; infra/ops/scraper
  only have continuation slices (ops #7 sits in unmerged #48 → a parallel PR would conflict).
  **analysis** held the only genuinely-unstarted, fully-offline roadmap items (#15 P3
  contradiction-finder, #17 P2 stance) — #17 wins on priority. **Backlog:** 2 open `daily/*` PRs
  (#48/#49) before this run — under 5.

### 2026-07-08 — scraper — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/45
- Source: roadmap:#10
- Summary: Roadmap **#10 (P3·M·scraper)** — **richer per-article metadata**, first slice: the pure,
  offline **extraction helpers** (D3 network viz / re-scrape deferred). New `extract_metadata(soup,
  url)` in `scraper/forbes_requests.py` pulls **canonical_url** (`<link rel=canonical>` → `og:url` →
  page URL, relatives resolved via `urljoin`), **published_date** (`article:published_time` → `<time
  datetime>` → `/YYYY/MM/DD/` path), **updated_date** (`article:modified_time` → `og:updated_time` →
  `""`), **section** (`article:section` → last `[class*=breadcrumb]` link → `""`), and **byline** +
  **byline_variants** (dedup across `meta[name=author]`, non-URL `article:author`, and
  `[rel=author]`/`[class*=author]`, first-seen order). Wired into `extract_article` via
  `**extract_metadata(...)`, preserving the existing keys — so the corpus back-fills these fields on
  the **next** `make scrape` (this is an extraction change, **not** a re-scrape; no regenerated data
  committed). TDD'd offline: +26 tests (`tests/test_forbes_metadata.py`) built from inline HTML
  fixtures. **§8.5 deepen:** source-precedence (published_time beats a stale `<time>`; modified_time
  beats og:updated), href whitespace stripping, whitespace-only/duplicate byline dedup, empty-
  breadcrumb section, and a monkeypatched **`extract_article` wiring** test proving the metadata flows
  into the merged article dict (+ 403/503 still return `None`). Also ruff-fixed the file's pre-existing
  unsorted import block (it was never gated — `make lint` only checks `tests/`). **Verification:** `make
  verify` green (**543 passed**, up from 517; ruff clean; dashboard builds). **Cold-path pick:**
  `plans/ready/` holds only 0008 whose remaining steps (26c QLoRA train / 26d live judged run / 26f
  decide) are owner-interactive/paid/compute — not unattended-safe; no user pins. Rotation was computed
  from **merged `main`** (the log is stale — missing the merged 06-26 #32 family, 06-27 #34 analysis,
  06-28 #35 ops, 07-04 #41 family, 07-05 #42 dashboard runs): by daily-date the last runs were infra
  (07-07), analysis (07-06), dashboard (07-05), family (07-04), scraper (07-01), ops (06-28). **family
  is now fully drained** (#22/#23/#24 all shipped), so the roadmap's family-payoff emphasis is
  exhausted; training (06-20) is least-recent but its only open item #27 is compute/conductor-heavy, and
  docs is drained — leaving **scraper #10** the least-recently-worked category with a clean,
  fully-offline unstarted item. **Backlog:** 4 open `daily/*` PRs, all stale `[skipped] backlog full`
  markers (#40/#39/#37/#36) — under the 5 threshold so work proceeded; owner should close those skip
  markers to keep the count down. **Future slices (in PR):** re-scrape/back-fill the existing corpus,
  surface the new fields in the manifest + dashboard, and add a byline-normalization pass.

### 2026-07-07 — infra — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/44
- Source: roadmap:#5
- Summary: Roadmap **#5 (P3·S·infra)** — **pre-commit hooks**. New `.pre-commit-config.yaml`
  with two `repo: local` hooks (no network fetch — they reuse the pinned `.venv` tools):
  **ruff check** on staged `tests/` (mirrors `make lint`/`verify`'s `LINT_PATHS := tests`) and a
  **JSON-validity** check on staged `data/analysis/*.json` so a malformed analysis artifact can't
  be committed. New TDD'd `tools/check_analysis_json.py` (pure `find_invalid()` + a CLI that takes
  pre-commit's staged filenames and gates on exit code; stdlib-only) + `make lint-json` (standalone
  runner) + `make hooks` (installer) + `pre-commit` added to `[dev]` deps + a README "Developing"
  section. **Scoping decisions:** (1) the JSON regex `\.json$` deliberately excludes committed
  `runs.jsonl` (JSONL, not JSON) and `.gitkeep`; gitignored artifacts (`embeddings*`,
  `geo_llm_registration`) never stage. (2) **Dropped a ruff-*format* hook** I first drafted:
  running it `--all-files` reformatted 14 pre-existing test files (+726/-308) — the committed tests
  aren't `ruff format`-clean and a repo-wide sweep is out of scope, so I matched the repo's actual
  enforced policy (`make verify` runs `ruff check`, not `ruff format`; formatting stays on-demand via
  `make fmt`). This keeps `pre-commit run --all-files` **green out of the box**. **§8.5 deepen:** +13
  tests incl. the real subprocess CLI contract pre-commit relies on, `main([])` default-glob mode,
  unicode + bare-scalar validity, and a pre-commit-guarded integration test that runs the actual
  configured hook against the real corpus (skips cleanly where pre-commit is absent, like the
  responsive check). **Verification:** `make verify` green (**517 passed**, ruff clean, dashboard
  builds); `pre-commit validate-config` OK; `pre-commit run --all-files` → both hooks Passed;
  `make lint-json` exit 0. **Cold-path pick:** `plans/ready/` holds only 0008 whose remaining steps
  (26c QLoRA train / 26d live judged run / 26f decide) are all owner-interactive/paid/compute — not
  unattended-safe; no user pins. Category rotation over the last 7 runs (training×3, scraper×2,
  analysis×1, docs×1) left **infra/dashboard/family** absent; infra was least-recently-worked
  (last 2026-06-02) and its only remaining items are P3 (#5 here, #7 structured logging) — picked #5
  (smaller, fully offline/deterministic). **Backlog:** 4 open `daily/*` PRs, all stale
  `[skipped] backlog full` markers (#40/#39/#37/#36) — under the 5 threshold so work proceeded;
  owner should close those skip markers to keep the count down.

### 2026-07-06 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/43
- Source: roadmap:#14
- Summary: Roadmap **#14 (P2·L·analysis)** — **entity co-occurrence graph**, first slice: the
  pure/offline **builder** (D3 network viz deferred to a later slice). New
  `analysis/entity_graph.py` reads `entities.json`'s `per_article` lists and emits committable
  `entity_graph.json` — nodes = people/orgs (`article_count`/`total_mentions`/`degree`), edge
  weight = shared-article count, plus `top_pairs`. **§8.5 deepen:** a default, overridable
  boilerplate **exclude** set (author byline "George Calhoun/Calhoun/Rafael/Stevens" + photo
  credits "Getty Images/AFP") so the graph reflects who he *writes about* — on the real corpus
  this cut noise edges 317→201 and surfaced the real hubs (Fed, Powell, Treasury, PCE, Jack Ma,
  Ant, Larry Summers). `run()` + `python -m analysis.entity_graph` CLI (`--dry-run`, `--top`,
  `--min-cooccur`, `--min-mentions`, `--exclude`/`--no-exclude`) + `make entity-graph` +
  architecture doc note. TDD'd: +21 tests (`test_entity_graph.py`). `make verify` green (**457
  passed**, ruff clean, dashboard builds); real corpus → 40 nodes / 201 edges, artifact valid.
  **Cold-path pick (stale-log correction):** `plans/ready/` holds only 0008 (26c–26f
  owner-interactive/paid/sibling-repo); no pins. The run history here is **missing the merged
  06-26/06-27/06-28 entries** (`#32` year-in-review, `#34` intellectual-arc, `#35`
  conductor-preflight — a stale-merge log regression), so rotation was computed from **merged
  code on `main`**: within `analysis`, #11 (P1) is the owner-gated paid backfill
  (`verdict_backfill.py` exists) and #13 is merged (`intellectual_arc.py`), leaving **#14** the
  top unstarted, unattended-safe item. **Env note:** started on a dirty
  `daily/2026-07-05-reading-room` tree (not `main`); its uncommitted local extras (a
  `serve_dashboard.py` tweak + regenerated data, not part of PR #42) were **stashed**
  (recoverable, `stash@{0}`) to cut this branch cleanly off `origin/main`. **Future slices (in
  PR):** entity alias-merging (Fed / the Federal Reserve / Jerome Powell), per-node neighbor
  lists, and the dashboard D3 network tab.

### 2026-07-01 — scraper — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/38
- Source: roadmap:#9
- Summary: Roadmap **#9 (P2·M·scraper)** — coverage audit vs the author index. New
  `scraper/coverage_audit.py` is the outward-looking mirror of `manifest_check` (#8): it compares
  the URLs we **have** (`data/manifest.json`) against a **discovered** set (the author's full
  Forbes footprint via Wayback CDX) and reports what's missing and *when* — `missing_urls`,
  `by_month` `{have, discovered, missing}`, `gap_months`, and contiguous `missing_ranges`
  (`2021-03..2021-04`). Pure `audit_coverage(manifest_articles, discovered_urls)` +
  `parse_article_url` (scheme-/www-/query-insensitive canonical keys from the
  `/YYYY/MM/DD/slug/` path) + `contiguous_month_ranges` + `format_report`, all TDD'd (31 new
  tests, offline). Live Wayback discovery sits behind an injectable seam (`discover` callable /
  `--urls-file`) so tests stay network-free. `run()` + `python -m scraper.coverage_audit` CLI
  mirrors `manifest_check`: report-only exit 0 by default, `--strict` gates CI, `--json` for
  machines. Added `make coverage-audit` + a `scraper/README.md` section. **Cold-path pick:**
  no ready plan, no user pins, and `scraper` was the least-recently-worked non-piled-on category
  with a not-started P2 (`docs` #28 already merged in #31; `analysis`/`family` had fresh open
  PRs #34/#32). Live smoke: 264 CDX URLs → 176 keys vs manifest's 176 → **100% coverage** today,
  corroborating #8's duplicate-slug finding. `make verify` green (377 passed, ruff clean,
  dashboard builds).

### 2026-06-25 — docs — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/31
- Source: roadmap:#28
- Summary: Roadmap **#28 (P3·S·docs)** — two contributor docs that capture knowledge previously
  only derivable by reading source. **Cold-path pick:** no unattended-runnable hot-path step
  left (0008's 26c/26d need owner compute, 26e is a sibling-repo `models.yaml` edit, 26f shipped
  in #30), no user pins, and `docs` is the least-recently-worked category (never appears in the
  last-7 run history). (1) `docs/conductor-contract.md` — the **formal** LLM contract behind
  `architecture.md §3`'s overview: exact chat + embeddings call shapes, return values,
  `model="auto"` + `(tier, function)` routing, `model_used` extraction via `model_extra`, the
  retry convention, tiers table (T1/T2/T3 + the paid-T3 `allow_remote` guard), and error modes
  incl. the `_conductor_up()` health-check seam used by the owner-gated eval CLIs (exit-2 abort).
  (2) `docs/runbooks/adding-an-analysis-module.md` — step-by-step for the next module
  (roadmap #13–#17): the `run(articles)` shape + shared `utils` helpers, the three-edit
  `__main__.py` wiring with `_should_run`/`_log_run` (fingerprint-skip for free), optional
  dashboard injection (`PLACEHOLDERS` + `_EMPTY_DEFAULTS` + template placeholder), and offline
  testing. Both linked from `docs/INDEX.md` (new "Contributor guides" section) and back-linked
  from `architecture.md` §2/§3. All facts verified against source
  (`analysis/{__main__,utils,predictions,semantic_search,psychoprofile,rag_eval}.py`,
  `viz/build_dashboard.py`, `Makefile`). Pure docs — no code, no conductor, no compute.
  `make verify` green (**333 passed**, ruff clean, dashboard smoke build). Roadmap #28 is a
  human-curated file the agent can't edit, so marking it `(done)` is left to the owner.

### 2026-06-20 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/26
- Source: plan:ready/0008
- Summary: Plan 0008 step **26e — register the fine-tune + let Ask Dad answer via it behind a
  flag (default off).** The conductor `models.yaml` registration lives in the **sibling**
  `local-llm-conductor` repo (out of scope for an unattended run), so I shipped the in-repo,
  deterministic half: the plumbing that lets the owner flip the fine-tune on once registered,
  with **zero behavior change until then**. (1) `analysis/geo_llm_status.py` now reads an
  owner-dropped marker `data/analysis/geo_llm_registration.json` (`finetune_registration`),
  replacing the hardcoded `"adapter": False` — it surfaces a `finetune` block in `geo_llm.json`
  and flips the 26e pipeline step to **done** when present (None/absent → stays not-done). (2)
  Ask Dad grows a **self-revealing, default-off** "Geo-LLM fine-tune" toggle in
  `dashboard/template.html`: hidden until `GEO_LLM_DATA.finetune.model_id` exists, and even when
  shown it defaults off → the chat keeps the existing RAG `model:"auto"` route; flipped on, the
  request routes to the registered `model_id` (+ the marker's optional `function`/`tier`). (3)
  Marker gitignored (owner/local, mirrors the sibling `models.yaml`); toggle + marker schema
  documented in `training/README.md`. §8.5 deepen: the reader tolerates a **malformed
  hand-authored marker** (invalid JSON / non-object → "not registered") so an owner typo can't
  take the whole Geo-LLM tab snapshot down. TDD'd: +12 tests (`tests/test_geo_llm_status.py`
  registration + 26e-flip; new `tests/test_dashboard_geo_flag.py` for the toggle plumbing).
  `make verify` green (**324 passed**, ruff clean, dashboard smoke build). End-to-end smoke:
  dropped a temp marker → `finetune` populated, 26e flips to done (5/6), built `index.html`
  inlines `model_id` (toggle reveals); removed it → reverts to `null`. **Still owner-interactive
  (not done here):** the `models.yaml` edit in `local-llm-conductor`, and 26f's live judged
  fine-tune-vs-RAG decision. Plan 0008 stays in `plans/ready/` (26f remains).

### 2026-06-19 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/25
- Source: plan:ready/0008
- Summary: Plan 0008 step **26d prep** — a deterministic builder that seeds the voice-eval's
  input. The 26d harness (#21, on `main`) consumes `eval/voice_trials.json`, but the only input
  today is the hand-authored placeholder `eval/voice_trials.example.json`. New
  `analysis/voice_trials.py` + `make voice-trials` turns 26a's `data/training/heldout.jsonl` into
  a real `voice_trials.json` **skeleton**: each trial's `prompt` (held-out user turn) + a
  length-balanced `real` Calhoun excerpt filled in, `rag`/`finetuned` left as paste-here
  placeholders for the owner. **Leakage-free by construction** (prompts come from the held-out
  split, which 26a already builds to exclude the #25 RAG-eval articles). Pure/offline (stdlib,
  no conductor, no paid T3 — safe unattended). `--limit`/`--seed` for reproducible sampling;
  malformed records skipped. §8.5 deepen: `real` prefers a **sentence boundary** (else word +
  ellipsis) so a mid-thought fragment can't tip the blind judge that it's an excerpt. The
  generated file embeds real bodies → **gitignored** like `heldout.jsonl`; committed deliverable
  is builder + 15 TDD tests + make target + README. **No dependency on the unmerged #23/#24** —
  branches off `main`. `make verify` green (**250 tests**, +15). Verified on the real split (8
  trials `v01..v08`, fed straight into `voice_eval.evaluate` — accepted). Plan 0008 stays in
  `plans/ready/`: 26c training, 26d live judged run, 26e (`models.yaml`), 26f (decide) all remain
  owner-interactive. Owner's next step: `make voice-trials`, paste the two model answers, run
  `make voice-eval`.

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
