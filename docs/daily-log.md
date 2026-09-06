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

### 2026-09-06 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/88
- Source: roadmap:dashboard (least-recently-worked category; items #18–#21 all shipped, so a defect in one)
- Summary: **The Raw Corpus tab promises "Every article, searchable and sortable" — the two
  halves didn't compose.** `renderCorpus()` held the chosen sort in a local `currentSort`, but
  only the `th` click handler ever applied it; the search box and the year/theme selects each
  re-rendered with `render(getFiltered())`, silently dropping the sort back to date-descending.
  Measured live in headless Chromium on the real 180-article corpus: sort by Title → first row
  *"'Hedge Funds' Got Clipped By Epic Fury"*; then pick a year → *"Is The U.S. 'Gas Tank' Running
  On Empty?"*, i.e. date order again. **Nothing disclosed it** — the header carried no sort
  indicator at all, so the table looked title-sorted while it was date-sorted. Every control now
  routes through one `renderCorpusView()` (`getFiltered()` narrows → `sortRows()` orders), the
  sorted column is marked `aria-sort` + an arrow, and `cursor:pointer` was narrowed to the three
  genuinely sortable `th`s (it was on Tags/Theme too, advertising a click that did nothing).
  **A latent crash found by the tests, not by reading:** the old comparator did `a[key] || ''`,
  so a missing/zero `word_count` became `''` and the *descending* branch called
  `vb.localeCompare(va)` on a **number** — `TypeError: vb.localeCompare is not a function`, which
  kills the table. No article carries a zero `word_count` today (min 267), but the manifest schema
  permits it and Corpus II ingest will produce it, so the comparator now keeps missing numerics on
  the numeric path. **§8.5 deepen:** a filter matching nothing left a bare header row with *no
  explanation* (the Track Record tab already says "No predictions match your filters"); a
  `#corpus-status` line now reports `180 articles` / `Showing 27 of 180 articles` / an explicit
  no-match message. Also added a regression guard for `deepLinkToCorpus` — the shipped Ask Dad
  citation deep-link (#19) clears the corpus filters by dispatching `input`/`change` at the
  controls, so it depends on exactly the listener wiring this PR rewrote; it passes before and
  after, which is the point. **Testing approach worth keeping:** `tests/` had *ten* dashboard test
  files and every one of them greps `template.html` for source strings — no test had ever executed
  the dashboard's JS. This adds a second layer: the page is rendered from `template.html` with a
  **synthetic** 4-article manifest (deliberate — no real article text in fixtures, and the titles
  sort differently from the dates so a lost sort is visible) and driven in headless Chromium,
  skipping cleanly when Chromium can't launch so CI stays green. **TDD'd:** +15 tests, proved
  red→green against `origin/main`'s template — **11 of 15 fail** without the fix, 15/15 with it;
  the 4 that pass either way are baseline guards. One test (`test_sort_survives_a_search`) was
  **vacuous when first written** — word-count-ascending happened to equal date-descending on that
  subset, so it would have passed with the bug; rewritten to a discriminating assertion and
  re-proved red. **Offline / unattended-safe:** no conductor, network, LLM or new dependency
  (Playwright was already a scraper dep); **no data artifact committed**. **Verification:**
  `make verify` green — **1007 passed**, ruff clean, dashboard builds; `make verify-responsive`
  **10/10** live checks pass (the CSS change didn't regress the phone reflow). Baseline measured,
  not assumed: a clean `origin/main` worktree collects **992** (991 passed + 1 environment skip —
  `pre-commit not installed`), so the delta is exactly the **+15** added here. **Backlog:** 6 open
  `daily/*` PRs (#82–#87) at start — under 8; §3 resumed none (all `ready-for-review`, none
  `in-progress`); `main` green. **Near-miss worth recording:** `git stash push <path>` with a
  clean path stashes *nothing*, so the paired `git stash pop` reached for **stash@{0} — a
  pre-existing stash from an earlier daily run** ("weekly-cron regenerated artifacts"). It aborted
  because of the dirty `data/` files and the entry survived, but the lesson is: **never pair
  stash/pop blind in this repo — there are 4 old stashes.** Use `git checkout <ref> -- <path>` for
  red→green proofs. **Deferred:** (1) on phones the corpus `thead` is visually hidden by the card
  reflow, so sorting is *unreachable* there — needs a mobile sort control, a design call, not a
  bugfix; (2) `build_dashboard` injects raw JSON into a `<script>` block, so a future document
  containing `</script>` would break the whole page — zero instances in the corpus today, but
  Corpus II email/HTML ingest makes it reachable; (3) two manifest entries slugged
  `george-calhoun` carry no date (the author index page, scraped by mistake) — a scraper concern.
  **NB:** `docs/plans/ready/0008-geo-llm-finetune.md` is **finished** (26a–26f shipped, D15 records
  the verdict) but still sits in `plans/ready/`, so §4 picks it up and discards it every run — the
  **fifth** ask that the owner move it to `plans/done/` to free the hot path.

### 2026-08-18 — family — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/81
- Source: roadmap:#21 (defect in the shipped Reading Room) — duplicate-slug fallout #77/#80 didn't reach
- Summary: **The Reading Room's "Newer ←" button re-opened the article you were already on.**
  `build_reading_room()` emits one entry per input record and chains them with
  `prev_slug`/`next_slug`; the manifest's 23 `http`/`https` twins reach it through `themes.json`,
  so the same article sat **twice in a row** in the reading order and its neighbour link pointed at
  **its own slug**. The dashboard resolves those links through `bySlug[slug]` — a map that *cannot*
  hold a slug twice — so the click re-opened the current article. Measured on the real corpus,
  regenerating **both sides from the same `themes.json`** (not trusting the stale file on disk):
  index rows **197 → 175**, duplicate rows **22 → 0**, self-referential links **44 → 0**, and the
  "Newer" walk **7 → 175 of 175** articles. **No article lost or gained** — only duplicate rows
  removed. This is the **fifth** reader carrying this defect; PR #80 audited for a fifth and
  concluded there wasn't one, because it checked direct *manifest* readers and `reading_room.py` is
  a **second-order** reader (it loads `themes.json`'s `.articles`, a derived artifact, and never
  touches the manifest). **TDD'd:** +7 tests, six red first for the right reason; the
  first-seen-wins tie-break was **proved non-vacuous** by implementing last-wins and watching it
  fail. **§8.5 deepen:** (1) probed every other second-order reader empirically — ran each builder
  on the real input vs a deduped copy and diffed: `anthology.corpus_span`/`signature_pieces`,
  `year_in_review.articles_for_year`/`top_themes` and `intellectual_arc.arc_by_year` are **all
  affected** (the 2022 digest counts **34** columns for **28**). But those are *count skew from a
  stale derived input*, not broken structures, so the fix is regenerating `themes.json`, **not**
  deduping at each reader — deduping there would hide the staleness. I **verified** the self-heal
  rather than inheriting the claim: `load_articles()` now returns **176**, and the corpus fingerprint
  is `a5cc3a1be358` vs the `593079338772` recorded by themes/linguistic/entities/predictions/
  semantic_search/psychoprofile, so all six **re-run** on the next `make analyze`. The Reading Room
  needed the builder fix anyway: a slug-keyed chain is a *structural* invariant, not a count.
  (2) Found a second, unrelated defect while confirming that regeneration path: **`make reading-room`
  did not exist.** It is documented in the README (3× with ARGS examples), in the module docstring,
  in `.gitignore`, and — worst — in the **dashboard's own empty state**, which tells the family
  "Run `make reading-room` then `make dashboard`". Doing that printed `No rule to make target`.
  `make voice-style` was missing the same way (README + `voice_eval`'s docstring; the capability
  existed as `--style-only`). Added both, and guarded the class with a test that pins every `make`
  target documented **in a code context** to a real rule — two prose false positives ("columnists
  make predictions") drove the extractor to read only fenced blocks / backticks / `<code>`.
  `make voice-style` reproduces D15's published numbers exactly (fine-tune TTR 0.352 vs real 0.704).
  **Offline / unattended-safe:** stdlib only, no conductor/network/LLM, no re-scrape, **no data
  artifact committed** (`reading_room.json` is git-ignored; I deleted the `voice_style.*` files my
  own verification run produced). **Verification:** `make verify` green — **891 passed** vs **852**
  on `origin/main`, ruff clean, dashboard builds. **Backlog:** 2 open `daily/*` PRs (#78, #80) at
  start — well under 8; §3 didn't resume either (both `ready-for-review`); `main` green.
  **Hot path:** plan **0008 is finished** — 26a–26f all shipped and D15 records the 26f verdict —
  but it still sits in `plans/ready/`, so §4 has picked it up and discarded it every run since
  06-24. I left the file where it is rather than move it in an unrelated PR; **the owner should move
  `docs/plans/ready/0008-geo-llm-finetune.md` to `docs/plans/done/`** to free the hot path.
  **NB (fourth ask):** the corpus-ingest work (PR **#79**) still has no plan in `docs/plans/ready/`,
  so §4 still can't see it; it remains higher value than anything left on the roadmap.

### 2026-08-15 — scraper — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/77
- Source: roadmap:#8 (follow-up) — the root cause PR #76 deferred yesterday
- Summary: **The analysis pipeline was reading 199 articles for 176 real ones.**
  `data/manifest.json` carries 23 duplicate-slug entries — all `http://`/`https://` twins naming
  the **same raw file** — and both corpus walkers read that file once per entry, so **10.2% of the
  body text every builder analyzed was duplicated** (368,778 → 331,050 words). This is the repo's
  longest-standing known defect: **PR #18** (06-13) *found* it and closed it as "a separate
  owner-reviewed follow-up"; **PR #38** (07-01) corroborated it from outside; **PR #76** (08-14)
  proved it *corrupts output* (3 of Tesla's 23 observations were the same sentences counted twice),
  fixed one builder locally, and deferred the root: "the **root** duplicate-slug bug in
  `load_articles()` still inflates every other corpus-walking builder." New shared
  `analysis.utils.dedupe_manifest_entries()` (one entry per raw `file`, first-seen order) wired into
  `load_articles()` → **every** analysis builder is immune, with no per-builder de-dup.
  **§8.5 deepen:** found the *same defect* a second time in `training/prepare.py`, which walks the
  manifest directly — its train/held-out split was already safe (keyed by slug), but
  `finetune.jsonl`/`instruct.jsonl` are written **per manifest entry**, so 23 articles appeared
  **twice** in the fine-tune corpus, silently over-weighting them in any plan-0008 QLoRA run.
  **Mistake worth recording:** I first built a `dedupe_articles()` + `--fix` into `manifest_check.py`
  before discovering `scraper/manifest_dedup.py` (merged 08-13) already does all of it, better
  (query-string handling, `--backfill-hashes`, owner-gated `--in-place`) — I **reverted** that commit
  rather than ship a duplicate abstraction, and left the revert in the history deliberately. The
  lesson: `make <target>` and `.PHONY` are a faster inventory of existing tooling than `ls`.
  That tool stays owner-gated (report-only), which is *why* the readers needed their own defence.
  **TDD'd:** +14 tests (`test_analysis_utils.py` 8→19 covering the pure helper, the loader, date
  sort and absent files; `test_prepare.py` 12→15 driving the real `run()` over a tmp corpus), both
  proved **red-green** (fix reverted → 1 and 3 failures; restored → green). **Offline /
  unattended-safe:** stdlib only, no conductor/network/LLM, no re-scrape, **no data artifact
  committed**. **Verification:** `make verify` green — **833 passed** (vs **819** on `origin/main`,
  +14), ruff clean, dashboard builds; `make contradictions` on **`main`'s own builder** (no #76
  changes) now finds **4** flips of 71 scanned (was 2), with **Tesla at 20** — the exact number #76
  reached via its own builder-local de-dup, i.e. the root fix subsumes it. **Stale artifacts, by
  design:** `themes.json`/`linguistics.json`/`entities.json` each still hold **199** `per_article`
  records; I did not regenerate them (large committed-data diff + `entity_graph`/`entity_stance`/
  `intellectual_arc` would cascade). They self-heal — the corpus fingerprint moves
  `5930793…` → `a5cc3a1…`, and `5930793…` is exactly the value recorded for the last `themes` run,
  so fingerprint-skip re-runs every module on the next weekly `make analyze`. **Backlog:** 1 open
  `daily/*` PR (#76) at start — well under 8; §3 didn't resume it (`ready-for-review`, not
  `in-progress`); `main` green. **Cold-path pick:** hot path holds only plan 0008
  (owner-interactive); no user pins; the roadmap is drained of unattended-safe unstarted items, so —
  as on 08-14 — I took the **most-deferred** item instead of strict rotation, and it happens to sit
  in **scraper**, the least-frequently-worked viable category in the last 7 runs (analysis ×3,
  dashboard ×2, scraper ×1, training ×1). **Deferred:** `make manifest-dedup ARGS="--apply
  --in-place --backfill-hashes"` to make the manifest itself *honest* (199 → 176, missing hashes →
  0) — owner-gated and no longer load-bearing for correctness. **NB for the owner (second ask):**
  `docs/corpus-ingest-spec` is **still unpushed/unmerged** and its 1401-line plan is not in
  `docs/plans/ready/`, so §4 cannot see it; that is almost certainly higher value than anything
  left on the current roadmap.

### 2026-08-05 — scraper — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/64
- Source: roadmap:#10
- Summary: Roadmap **#10 (P3·M·scraper)** — the explicitly-deferred **byline-normalization pass**
  (the #10 first slice, PR #45, shipped the metadata extractor but left byline cleanup as a future
  slice). `extract_metadata` collected raw byline variants but did **zero** cleanup — `byline` was
  just `variants[0]`, so a scraped page yielded messy authorship (`By George Calhoun`,
  `George Calhoun, Contributor`, or the glued author-class form `George CalhounContributor`). This
  slice adds one pure, offline `normalize_byline(name)` in `scraper/forbes_requests.py`: collapses
  whitespace, strips a leading `By`/`By:` prefix, and strips a trailing Forbes role suffix
  (`Contributor`/`Senior/Staff/Former/Guest Contributor`, comma-separated **or** glued). It's
  conservative — a clean name, or a non-`Contributor` role (`Jane Doe, Staff Writer`), passes
  through untouched. **§8.5 deepen:** `extract_metadata` now emits a **`bylines_normalized`** field
  (each raw variant normalized, empties dropped, deduped in first-seen order — the distinct clean
  authors) and picks the primary `byline` as its first entry, so an all-noise first variant
  (`Contributor` → `George Calhoun`) no longer wins; `byline_variants` stays **raw** for provenance.
  Docs updated (`scraper/README.md` table + `docs/architecture.md` scraper section). **TDD'd:** +20
  tests (`tests/test_forbes_metadata.py`, 26→46) — passthrough/prefix/role/glued/whitespace/empty,
  the metadata-wiring (normalized primary vs. raw variants), normalized-variant dedup + co-author
  order + drop-to-empty, and edge cases (trailing period, role-only, comma spacing, uppercase `By`,
  non-`Contributor` passthrough) + the shape guard. **Offline / unattended-safe:** pure stdlib
  string ops on an already-parsed tree; no conductor/network/LLM, **no re-scrape** (an extraction
  change — the corpus back-fills clean bylines on the next `make scrape`; no regenerated data
  committed). **Verification:** `make verify` green — **767 passed** (up from 747 on main; +20),
  ruff clean (tests/ + the touched `forbes_requests.py`), dashboard builds. **Backlog:** 4 open
  `daily/*` PRs before this run (#63 aliases + #53 stance-viz + skip markers #58/#59) — under 5; §3
  didn't resume (#63/#53 are `ready-for-review`, not `in-progress`). **Cold-path pick:** hot path
  drained (only 0008 remains — all owner-interactive compute/paid/sibling-repo); no user pins.
  Absent-from-last-7 categories (infra/family/docs) are all drained (roadmap #1–7, #21/#23/#24, #28
  shipped); of the remaining viable categories **scraper** is least-recently-worked (2026-07-08 vs
  analysis 08-04 / training 08-03 / dashboard 08-01), and #10 had a genuinely-unstarted,
  fully-offline slice that needs no re-scrape and no unmerged code. Chose it over "alias
  `contradictions`" (the other 08-04 deferral) because that depends on `analysis/entity_aliases.py`,
  which is only on the **unmerged** #63. **Deferred:** re-scrape/back-fill the corpus with the new
  fields, and surface `byline`/`section`/`canonical_url` in the manifest + dashboard.

### 2026-08-04 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/63
- Source: roadmap:#14
- Summary: Roadmap **#14 (analysis)** — the long-deferred **entity alias-merge** gap. The spaCy
  extractor emits many spellings for one subject (`the Federal Reserve` / `The Federal Reserve` /
  `Federal Reserve` / `Fed`; `Covid`/`COVID`; `Treasury`/`Treasurys`; `Powell`/`Jerome Powell`;
  `Ma`/`Jack Ma`), so downstream builders split a single subject across several nodes/trajectories.
  This slice adds one shared, transparent, owner-editable canonicalizer and wires it into **two**
  builders. (1) New pure/offline `analysis/entity_aliases.py`: `canonicalize(name)` whitespace-
  normalizes, strips a trailing possessive (straight **and** curly `'s` — the extractor only strips
  straight) + a single leading "the", then applies a curated corpus-specific ALIAS map (lowercased
  keys, every value a fixed point). (2) `entity_graph.py`: aliased default-on with `--no-aliases`
  off-switch + `aliases` meta param; `entity_nodes` collapses per-article by canonical id *before*
  global aggregation so `article_count` stays a true distinct-article count; exclude matches the
  canonical name. Regenerated `entity_graph.json`: 4 Fed nodes → 1 (69 articles, degree 28),
  201→192 edges. **§8.5 deepen:** extended the same seam to `entity_stance.py` — because it searches
  bodies for surface names, it searches with each *raw* name but groups results under the canonical
  id and de-dups sentences that name two variants (set union) so a sentence scores once; regenerated
  `entity_stance.json` (Fed variants → one 63-article trajectory). Architecture.md updated for both
  builders. **TDD'd:** +32 tests (`tests/test_entity_aliases.py`: strip/alias/possessive/passthrough
  + fixed-point & lowercase-key hygiene) plus alias-merge sections in `test_entity_graph.py` and
  `test_entity_stance.py`. **Offline / unattended-safe:** no conductor/network/LLM; both regenerated
  artifacts are text-free (names/years/scores only) and read committed `entities.json`. **Verification:**
  `make verify` green — **789 passed**, ruff clean, dashboard builds. **Backlog:** open `daily/*` PRs
  under 5; §3 didn't resume any in-progress PR. **Cold-path pick:** hot path drained, no user pins;
  **analysis** was the least-recently-worked viable category and #14's alias-merge was the most-deferred
  item (raised across #14/#15/#17 runs). **Deferred:** aliasing `contradictions`, and a dashboard viz
  for the stance trajectories (PR #53).


### 2026-08-03 — training — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/62
- Source: roadmap:#27
- Summary: Roadmap **#27 (P3·M·training)** — the embedding-model comparison harness, its
  **deferred "curated gold query set" slice**. The `analysis/embedding_compare.py` builder shipped
  (three #27 commits) but explicitly ships only a "deliberately small starter set" (5 queries) and
  its hand-authored `relevant_slugs` were **unchecked** — a typo'd / renamed slug silently scores 0
  in a live retrieval pass rather than erroring, and with no gold labels the harness's retrieval
  metrics (precision@k / recall@k / MRR) are all zero. This slice closes that gap **fully offline**:
  (1) new pure `validate_queries(queries, corpus_slugs)` (unknown slug, blank query, empty /
  duplicate labels, duplicate query text — 1-based messages); (2) a `load_corpus_slugs()` reading the
  committed **text-free** `data/manifest.json` + an offline `--check` CLI mode (runs *before* the
  conductor gate, so it works unattended on CI / a fresh clone with no candidate models and no
  conductor) + `make embedding-queries-check`; (3) **expanded the gold set 5 → 13 queries** across
  Dad's major beats (EU Hamiltonian, Buffett/value, Ant Group, GameStop, CPI-artifact, CHIPS Act,
  Fed funds rate, tariffs/recession, crypto, China Covid-data, Alibaba value-trap, Tesla/S&P 500,
  China Japanification), every `relevant_slug` mapped to a real manifest article. **§8.5 deepen:** a
  committed-set regression guard test (the checked-in gold set must stay valid against the checked-in
  manifest) + an architecture.md note on the `--check` guard. **TDD'd:** +14 tests
  (`tests/test_embedding_compare.py`, 40→54) — validator cases, the manifest loader, `--check` exit
  codes / offline behavior, and the committed-set guard. **Offline / unattended-safe:** no conductor,
  network, or LLM; the gold set is text-free (queries + public slugs), committed like
  `eval/questions.json`; the harness output `data/analysis/embedding_compare.json` (a regenerated
  artifact) is **not** touched. **Verification:** `make verify` green — **740 passed** (up from 726 on
  main; +14), ruff clean, dashboard builds; `make embedding-queries-check` → *"13 queries; every
  relevant_slug resolves to one of 176 corpus articles."* **Backlog:** 4 open `daily/*` PRs before this
  run (#61 anthology + #53 stance-viz + skip markers #58/#59) — under 5; §3 didn't resume (#61/#53 are
  `ready-for-review`, not `in-progress`). **Cold-path pick:** hot path drained (only 0008 remains —
  26c train / 26d live / 26e sibling-repo `models.yaml` / 26f decide, all owner-interactive); no user
  pins. **training** is the least-recently-worked category (last 2026-06-20, absent from the last 7
  runs) and #27 had a genuinely-unstarted, fully-offline deferred slice; #25 shipped (plan 0007), #26
  is owner-blocked. **Deferred:** the #27 dashboard viz, and semi-automating gold-label candidates
  from the committed theme/entity artifacts.

### 2026-08-01 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/60
- Source: roadmap:#15 (deferred dashboard viz) + red-main regression fix
- Summary: **Fixed red `main`** first, then shipped the last orphaned analysis-builder viz.
  **(1) Regression fix:** a prior merge (PR #56, calhoun-isms tab) dropped the
  `CALHOUN_ISMS_DATA` const, the `/*__CALHOUN_ISMS_DATA__*/` `build_dashboard` placeholder, and its
  empty-default — so `renderCalhounIsms()` referenced an **undefined global** and **4
  `test_dashboard_calhoun_isms.py` tests were failing on `main`** (`make verify` red). Restored the
  three lines → main green (**718 passed**, was 4 failed / 714 passed). Confirmed live: clicking the
  Calhoun-isms tab renders real data with **0 console errors** (was a `ReferenceError`).
  **(2) Feature (roadmap #15 deferred viz):** every analysis builder had a dashboard tab except
  `contradictions.py` (merged #52). Added a **Second Thoughts** tab surfacing its mind-change
  finder — warmed/cooled cards per reversed-stance subject pairing his earliest vs. latest take,
  each quote deep-linking into the Raw Corpus, plus a direction filter. Wired like the
  Calhoun-isms / Reading Room tabs (`/*__CONTRADICTIONS_DATA__*/` → git-ignored
  `contradictions.json` with a valid empty-default; empty-board build prompt on CI / fresh clones).
  **TDD'd:** +8 guard tests (`tests/test_dashboard_contradictions.py`) — including the const +
  placeholder assertions that *would have caught* the calhoun-isms regression. **Offline /
  unattended-safe:** no conductor/network/LLM; builds only on merged `main`, independent of the
  open #53 (stance viz) tab. **Verification:** `make verify` green (**726 passed**, ruff clean,
  dashboard builds); real-corpus `make contradictions` → 2 defensible flips (Covid *warmed* 43 obs,
  Tesla *cooled* 23 obs); headless-Chromium browser pass (build artifact git-ignored) desktop
  1280×900 + phone 375×812 → 2 cards / 4 quotes / Warmed+Cooled badges, direction filter works,
  **0 console errors, 0px h-overflow** (15-tab nav wraps via the existing `flex-wrap`). **Backlog:**
  3 open `daily/*` PRs (#53 + skip markers #58/#59) before this run — under 5; §3 didn't resume
  (#53 is `ready-for-review`, not `in-progress`). **Cold-path pick:** hot-path drained (only 0008
  remains — all owner-interactive compute / paid / sibling-repo); no user pins; staler categories
  drained/blocked (family/docs/infra shipped, training #26 owner-blocked + #27 merged #54, scraper
  #10 blocked on re-scrape, analysis #11 owner-gated-paid). **Note — stale base:** this run's
  starting branch (`daily/2026-07-23-skip`) predated the merges of #54–#57, so §1 was re-run against
  the real `origin/main`; the red-main regression was discovered there. **Deferred:** entity
  **alias-merge** (Fed / the Federal Reserve / Powell still separate) would sharpen this tab, the
  Network graph, and the stance viz together.

### 2026-07-21 — dashboard — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/57
- Source: roadmap:#13 (deferred dashboard viz)
- Summary: Roadmap **#13 (P2·M·analysis)** deferred **viz slice** — a new **Intellectual Arc**
  dashboard tab surfacing the already-merged `analysis/intellectual_arc.py` builder (data layer
  shipped 2026-06-27). Until now its `intellectual_arc.json` (committed + **text-free**) sat on
  `main` with nothing rendering it. Thin offline dashboard layer over a committed builder — the
  exact analog of merged **#51** (network tab over `entity_graph`) / open **#56** (Calhoun-isms).
  New `renderIntellectualArc()` draws: the deterministic **narrative** + headline stats
  (span, dated pieces, first→last dominant theme, most-grown/most-declined); a **per-year stacked
  theme-composition** bar chart (segments reuse the shared `clusterColor()` palette so a theme
  reads the same as on Theme Map / Timeline; partial in-progress years dimmed & flagged); and
  **year-over-year shift cards** (rising / fading / emergent + any lead-theme change). Wired
  through `build_dashboard`'s `/*__INTELLECTUAL_ARC_DATA__*/` placeholder with an empty-arc stub
  (CI / fresh clones show a `make intellectual-arc` prompt). Because the artifact is **committed +
  text-free** (theme labels/shares + a deterministic narrative — no body excerpts), the tab renders
  **real data on merge**, unlike the git-ignored calhoun_isms/reading_room tabs — **no data artifact
  committed** (the build output `index.html` stays git-ignored). Also added desktop `nav {
  flex-wrap: wrap }` — the 13th tab overflowed the centered flex row (same fix as #56, but
  independently, since #56 is unmerged). **§8.5 deepen:** legend **click-to-trace** — clicking a
  theme rings its band (`box-shadow` inset) across every year and dims the rest; re-click clears
  (mirrors the Reading Room theme filter). **TDD'd:** +11 tests
  (`tests/test_dashboard_intellectual_arc.py`) — placeholder/empty-stub wiring, nav tab + dispatch,
  narrative/by_year/shifts rendering, `clusterColor` reuse, legend-highlight, and a nav flex-wrap
  guard. **Verification:** `make verify` green (**643 passed**, up from 632; ruff clean; dashboard
  builds) + a real-corpus headless browser pass (Playwright, local — build artifact git-ignored):
  desktop & phone both render the narrative + 35 theme segments with **no h-overflow and a clean
  console**, and the legend click dims 29/35 while ringing the selected theme's 6 year-segments,
  clearing back to 35 on re-click. Also **documented** the previously-undocumented
  `intellectual_arc.py` builder + the new tab in `architecture.md`. **Cold-path pick:** hot-path
  drained (only 0008 remains — 26c/26d/26e/26f all owner-interactive compute / paid / sibling-repo
  `models.yaml`); no user pins. The staler categories are drained/blocked: **family** (last 06-03)
  fully drained (#21/#23/#24 shipped), **docs** (06-25) drained (#28 shipped), **infra/ops** (07-07)
  drained (#7 structured-logging merged as #48 on 07-16, so #1–7 all shipped), **training** #26
  owner-blocked + #27 in flight (open #54), **scraper** #10 remaining slices blocked on a re-scrape
  (forbidden to commit regenerated data). That left the two genuinely-orphaned analysis builders
  with no merged dashboard viz — `intellectual_arc` **#13 (P2)** and `contradictions` **#15 (P3)**
  (calhoun_isms #16 / entity_stance #17 already have viz in flight on #56 / #53). Per §5b
  "highest-priority not-yet-started," **#13 (P2) wins over #15 (P3)** — and it's the higher
  family/emotional payoff (the sweep of Dad's focus over 7 years, Fed/Financial → Tariffs/Crypto).
  **Backlog:** 4 open `daily/*` PRs (#56/#55/#54/#53) before this run — under 5; §3 didn't resume
  (all `ready-for-review`, not `in-progress`). **Deferred (in PR):** deep-link a theme segment to
  the Theme Map filtered to that cluster; a small `contradictions` #15 tab as the last orphaned
  builder.

### 2026-07-16 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/52
- Source: roadmap:#15
- Summary: Roadmap **#15 (P3·M·analysis)** — **contradiction / mind-change finder**, builder slice
  (dashboard viz deferred, mirroring #14/#16/#17). New `analysis/contradictions.py`, a pure/offline
  builder in the `entity_graph`/`calhoun_isms` mould: reads `entities.json`'s frequent people/orgs +
  the corpus bodies, scores Dad's **stance toward each subject over time** via a small transparent
  polarity lexicon (positive − negative words on word boundaries, per sentence naming the subject),
  and emits gitignored `contradictions.json` — subjects whose mean stance **reversed sign** between
  his earlier vs. later writing, each with representative early/late quotes + `warmed`/`cooled`
  direction, sorted by swing. `run()` + `python -m analysis.contradictions` CLI (`--dry-run`,
  `--min-mentions`, `--min-observations`, `--min-delta`, `--max-sentence-words`, `--no-exclude`) +
  `make contradictions` + architecture note. **§8.5 deepen** fixed three quality bugs the first
  smoke run exposed: (1) **case-sensitive** proper-noun matching (so "Jack" ≠ the verb in "jack up
  the stimulus"); (2) a **word-band** on stance sentences (≤45 words) so the corpus's glued run-ons
  don't become bloated quotes; (3) **case-insensitive alias dedup** ("COVID"/"Covid" → one row).
  **TDD'd:** +25 tests (`tests/test_contradictions.py`). **Offline/unattended-safe:** stdlib only,
  no conductor/network/LLM; builds only on data already on `main` (does **not** depend on the
  unmerged #50 entity-stance PR). **Licensing:** artifact embeds body excerpts → gitignored
  (regenerate on demand), same posture as `calhoun_isms.json`/`reading_room.json`. **Verification:**
  `make verify` green (**592 passed**, up from 567; ruff clean; dashboard builds); real-corpus smoke
  (offline) → **2 clean, defensible flips** (Covid *warmed*, Tesla *cooled*) of 71 scanned subjects.
  **Resume/backlog:** §3 didn't resume — the 3 open `daily/*` PRs (#51 entity-network-viz, #50
  entity-stance, #48 structured-logging) are all `ready-for-review`, not `in-progress`; under the
  5-PR cap so work proceeded. **Cold-path pick:** `plans/ready/` holds only 0008 (owner-interactive
  QLoRA/paid-judge/sibling-repo `models.yaml`/decide — not unattended-safe); no user pins. Verified
  the more-stale categories are drained/blocked: family (06-03) fully drained (`reading_room`/
  `year_in_review`/`anthology` + On-This-Day auto-send all shipped), training's only item #27 is
  conductor/compute-heavy, docs #28 shipped, infra #1–7 shipped, scraper #10's remaining slices are
  blocked on a re-scrape (forbidden to commit regenerated data). That left **analysis #15** — a
  genuinely-unstarted (no `contradictions.py` existed), fully-offline, family-facing item in the
  established module pattern, fitting the roadmap's post-family "analytical-depth" emphasis.
  **Deferred (next slice):** dashboard tab + entity **alias merging** (Fed / the Federal Reserve /
  Jerome Powell still separate subjects, inherited from #14's builder).

### 2026-07-12 — analysis — ready-for-review
- PR: https://github.com/wcalhoun516/digital-dad/pull/49
- Source: roadmap:#16
- Summary: Roadmap **#16 (P3·S·analysis)** — **"Calhoun-isms": most quotable/aphoristic sentences per
  theme.** New `analysis/calhoun_isms.py`, a deterministic/offline builder modeled on `entity_graph.py`
  (#14): reads `themes.json`'s per-article theme assignments + the corpus bodies, scores every sentence
  with **transparent heuristics**, and emits `calhoun_isms.json` (top aphorisms per theme + an overall
  board). Gate (`is_quotable`): declarative, memorable word band (8–30), capitalized, no
  antecedent-needing opener (`But`/`This`/`It`/…), no URL noise. Score (`quotability_score`,
  deterministic additive): length term peaking ~14 words + bonuses for absolutes
  (`always`/`never`/`no one`), a definitional `X is …`, and contrast; penalties for attribution
  ("Powell said") and newsy digits. `run()` + `python -m analysis.calhoun_isms` CLI
  (`--dry-run`/`--top`/`--min-words`/`--max-words`/`--min-score`) + `make calhoun-isms` + architecture
  note. **§8.5 deepen:** `--min-score` filler filter + overall-board dedup-by-text. **TDD'd:** +24 tests
  (`tests/test_calhoun_isms.py`). **Licensing:** the artifact embeds body-text excerpts, so it's
  **gitignored** (regenerate on demand), mirroring `reading_room.json`. **Verification:** `make verify`
  green (**567 passed**, up from 543; ruff clean; dashboard builds); real-corpus smoke → 9 themes / 199
  articles, genuine aphorisms surfaced, 33 KB valid JSON correctly ignored by git. **Cold-path pick:**
  `plans/ready/` holds only 0008 (26c/26d/26f owner-interactive/paid/compute — not unattended-safe); no
  user pins. PR #48 (07-11 ops/structured-logging, on its own unmerged branch) is
  ready-for-review-but-unmerged, so §3 didn't resume it and a parallel logging PR off `main` would
  conflict. Rotation (last worked by category, from merged `main` + known open PRs): ops 07-11, scraper
  07-08, infra 07-07, analysis 07-06, dashboard 07-05, family 07-04 — training (06-20)/docs (06-25) are
  drained or conductor-heavy (#27), dashboard/family drained, leaving **analysis** the least-recent
  category with a genuinely-unstarted, fully-offline item: **#16**. **Backlog:** 1 open `daily/*` PR
  (#48) before this run — well under the 5 threshold.

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
