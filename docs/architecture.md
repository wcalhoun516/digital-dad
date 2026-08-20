# Architecture

`digital-dad` is a four-stage pipeline — **scrape → analyze → synthesize → present** —
with persistent artifacts at each stage and a single LLM abstraction (the *conductor*)
underneath everything that needs a model.

```
Forbes / Wayback ──scrape──▶ data/raw/*.json ──analyze──▶ data/analysis/*.json
                                  │ manifest.json                    │
                                  │                                  ├─▶ viz ──▶ dashboard/index.html
                                  └──────training──▶ data/training/   └─▶ on_this_day ──▶ emails + Gmail draft
```

## 1. Scraper (`scraper/`)

Discovers and extracts Dr. Calhoun's Forbes columns. **Three-tier fallback** at every step
so a single source going down doesn't break ingestion.

- `__main__.py` — CLI (`python -m scraper`). `discover_urls()` tries Playwright → sitemap
  → Wayback CDX; `extract_article()` tries requests+BS4 → Playwright → Wayback snapshot.
  Updates `data/manifest.json` and writes one `data/raw/{slug}.json` per article.
- `wayback.py` — CDX query for archived `forbes.com/sites/georgecalhoun/*` URLs; extracts
  title/date/body from the latest snapshot. Rate-limited (5s for web.archive.org).
- `utils.py` — `RateLimiter` (per-domain delays), exponential-backoff retry, `slugify`,
  `is_article_url` (filters to `/sites/georgecalhoun/`, excludes `/amp/` + pagination).
- `forbes_requests.py` — Tier-2 requests+BS4 extraction. `extract_metadata()` adds richer
  per-article fields (roadmap #10: canonical URL, published/updated dates, section, bylines).
  `normalize_byline()` cleans a raw byline (drops a leading `By`/`By:` and a trailing
  `Contributor`/`Senior Contributor` role, comma- or glued-form); `byline` is the first
  distinct normalized author, with `byline_variants` kept raw for provenance and
  `bylines_normalized` the deduped clean list. See `scraper/README.md`.

**Manifest schema** (`data/manifest.json`): `{last_updated, total_articles, articles:[{slug,
title, date, url, tags, word_count, file, content_hash}]}`. `content_hash` is the MD5 of the
body — the basis for change detection.

## 2. Analysis (`analysis/`)

CLI: `python -m analysis [modules] [--dry-run] [--force] [--remote] [--verbose]`. Modules run in
order: `linguistic · themes · entities · psychoprofile · semantic_search · predictions`.

**Logging** (`analysis/utils.py`): modules emit progress through a shared `log`
(`setup_logging()`, logger `digital-dad.analysis`, mirroring `scraper/utils.py`) rather than
`print`. `--verbose`/`-v` drops the level to DEBUG (e.g. themes' per-`k` silhouette scores).

**Corpus fingerprinting** (`__main__.py`): an MD5 over all article slugs + content_hashes.
Each completed module appends a line to `data/analysis/runs.jsonl` with the fingerprint it
ran against; on the next run a module is **skipped if the fingerprint is unchanged** (unless
`--force`). This is what makes the weekly cron cheap.

| Module | Output | What it does |
|--------|--------|--------------|
| `linguistic.py` | `linguistics.json` | Readability (Flesch-Kincaid, Gunning Fog), VADER sentiment, type-token + hapax ratios, distinctive words, sentence-length histogram. |
| `themes.py` | `themes.json` | TF-IDF + KMeans (k=4..10, silhouette-selected) clusters; quarter-binned topic timeline. |
| `entities.py` | `entities.json` | spaCy `en_core_web_sm` NER → top organizations & people by frequency + article spread. |
| `psychoprofile.py` | `psychoprofile.json` + `.md` | Map-reduce LLM analysis → narrative profile + 8 personality dimension scores. Logs cost to `runs.jsonl`. |
| `semantic_search.py` | `embeddings.npy`, `embeddings_meta.json`, `embeddings.json` | sbert-mpnet-v2 (384-dim) embedding index; cached + corpus-hash busted; flattened export with snippets for the dashboard. |
| `predictions.py` | `predictions.json` | Two-pass: extract falsifiable claims per article, then optional batched LLM verdict (pending/vindicated/wrong/mixed/unfalsifiable). Saves incrementally every 10 articles; resumable. |

`utils.py` — shared `load_manifest()`, `load_articles()`, `clean_text()` (strips Forbes
boilerplate), `chunk_text()` (sentence-aware), `save_analysis()`.

`load_articles()` yields **one article per raw `file`** via `dedupe_manifest_entries()`. The
committed manifest still carries 23 duplicate-slug entries (199 entries → 176 distinct files;
see [`../scraper/README.md`](../scraper/README.md)), and without this every corpus-walking
builder re-read those 23 bodies and counted their sentences twice — 10.2% of the analyzed text
was duplicated. Builders therefore need no de-dup of their own. `training/prepare.py` walks
the manifest directly and applies the same helper for the same reason.

> Adding a module? See the runbook: [`runbooks/adding-an-analysis-module.md`](runbooks/adding-an-analysis-module.md).

`on_this_day.py` — not part of the default analyze chain; run via `make on-this-day`. Pulls
RSS headlines, embeds them, finds the best-matching archive article by cosine similarity,
generates a 2–3 sentence intro in Dr. Calhoun's voice (conductor T2), renders an HTML email
to `data/cron/emails/`, logs to `data/cron/on_this_day.jsonl`.

`entity_graph.py` — also outside the default chain; run via `make entity-graph`. A pure/offline
**derived** artifact: reads `entities.json`'s `per_article` lists and emits `entity_graph.json`,
an undirected co-occurrence graph (nodes = people/orgs, edge weight = shared-article count).
Byline/photo-credit boilerplate is excluded by default (`--no-exclude` to keep it). Surface-form
variants are **canonicalized** first via `entity_aliases.py` — a small curated alias map (`the
Federal Reserve` / `Fed` / `Federal Reserve's` → `Federal Reserve`; `Powell` → `Jerome Powell`;
`Treasurys` → `Treasury`; `BLS` → `Bureau of Labor Statistics`) plus leading-"the"/possessive
stripping — so one subject stops splitting across nodes (`--no-aliases` to disable). Merging
happens per-article, so `article_count` stays a true distinct-article count. `entity_stance.py`
aliases too (`--no-aliases` to disable): it searches bodies with each *raw* surface name but groups
the results under the canonical id, de-duping sentences that name two variants so a sentence scores
once. No conductor/network. Surfaced in the dashboard's **Network** tab — a D3 force-directed graph
injected via `build_dashboard`'s `/*__ENTITY_GRAPH_DATA__*/` placeholder (empty-graph stub in
CI / fresh clones, prompting `make entity-graph`); it re-fits on viewport change like the other
pixel-sized chart tabs. (Roadmap #14.)

`entity_stance.py` — also outside the default chain; run via `make entity-stance`. A pure/offline
**derived** artifact: joins `entities.json`'s `per_article` lists to the corpus bodies and emits
`entity_stance.json`, a per-entity **yearly stance trajectory** (mean tone of the sentences that
name an entity, per year) plus warming/cooling trend boards. The dashboard **Stance** tab
(`renderStance` in `template.html`, injected via `/*__ENTITY_STANCE_DATA__*/`) draws these as a
D3 multi-line chart with the trend boards alongside; CI / fresh clones inline an empty-graph stub
and the tab shows a `make entity-stance` prompt. Because nltk/VADER is absent here, tone is a
**transparent heuristic** — a small curated polarity lexicon scored per sentence with a light
negation flip — so it surfaces *trends*, not ground-truth sentiment. The artifact is text-free
(names/years/scores only), so it's committable like `entity_graph.json`. Same byline/photo-credit
exclusion. No conductor/network. (Roadmap #17.)

`embedding_compare.py` — the **embedding-model comparison harness** behind decision **D2** ("evaluate
alternatives before swapping the pinned `sbert-mpnet-v2`"). Run via `make embedding-compare`;
owner-gated on conductor reachability. Following `rag_eval`/`voice_eval`, the one networked seam —
`embed(model_id, texts)` — is injected, so the ranking + comparison math is pure and TDD'd offline.
It ranks the corpus per query with each candidate model and reports two things: **retrieval quality**
(precision@k / recall@k / MRR against the committed, text-free gold set `eval/embedding_queries.json`)
and **baseline agreement** (top-k overlap + Kendall-tau of each candidate's rankings vs. the pinned
model — the label-free "is it safe to swap?" number). Writes `data/analysis/embedding_compare.json`
(owner-run, not committed). The gold set's hand-authored `relevant_slugs` are guarded offline by
`make embedding-queries-check` (`python -m analysis.embedding_compare --check`): it validates every
slug against the committed `data/manifest.json` — no conductor, no embedding — so a typo'd / renamed
slug fails loudly instead of silently scoring 0 in a live pass. A dashboard viz is still deferred.
(Roadmap #27.)

`calhoun_isms.py` — also outside the default chain; run via `make calhoun-isms`. A pure/offline
**derived** artifact: reads `themes.json`'s per-article theme assignments plus the corpus bodies,
scores every sentence for "quotability" with transparent heuristics (length band + aphoristic
markers like *always/never/no one*, minus attribution/newsy-digit penalties), and emits
`calhoun_isms.json` — the strongest aphorisms grouped by theme plus an overall board. Because the
artifact embeds short **body excerpts**, it is **git-ignored** (regenerate on demand), the same
posture as `reading_room.json`. Surfaced in the dashboard's **Calhoun-isms** tab (roadmap #16),
injected via `build_dashboard`'s `/*__CALHOUN_ISMS_DATA__*/` placeholder with an empty-board stub
in CI / fresh clones (prompting `make calhoun-isms`); each quote deep-links into the Raw Corpus tab
via the shared `deepLinkToCorpus()` helper. No conductor/network. (Roadmap #16.)

`intellectual_arc.py` — also outside the default chain; run via `make intellectual-arc`. A
pure/offline **derived** artifact: bins `themes.json`'s clustered articles by calendar year and
emits `intellectual_arc.json` — each year's theme composition (per-cluster share + a dominant
theme), the consecutive year-over-year `shifts` (rising / fading / emergent / vanished + any
change of lead theme), an `overall` summary (most-grown / most-declined theme across the span,
first→last dominant), and a **deterministic** prose `narrative` assembled from those numbers
(no LLM). Thin in-progress years are flagged `partial` so they can't anchor the conclusion. The
artifact is text-free (theme labels/counts/shares only), so it's committable like
`entity_graph.json`. No conductor/network. Surfaced in the dashboard's **Intellectual Arc** tab
— the narrative + headline stats, a per-year stacked theme-composition bar chart (segment colors
reuse the shared `clusterColor()` palette, so a theme reads the same as on the Theme Map /
Timeline; click a legend theme to trace its band across every year), and year-over-year shift
cards — injected via `build_dashboard`'s `/*__INTELLECTUAL_ARC_DATA__*/` placeholder (empty-arc
stub in CI / fresh clones, prompting `make intellectual-arc`). (Roadmap #13.)

`contradictions.py` — also outside the default chain; run via `make contradictions`. A
pure/offline **derived** artifact: reads `entities.json`'s frequent people/orgs plus the corpus
bodies, scores Dad's stance toward each subject sentence-by-sentence via a small transparent
polarity lexicon, and emits `contradictions.json` — subjects whose mean stance **reversed sign**
between his earlier vs. later writing, each with a representative early/late quote and a
`warmed`/`cooled` direction, sorted by swing. Because the artifact embeds **body excerpts**, it is
**git-ignored** (regenerate on demand), the same posture as `calhoun_isms.json` / `reading_room.json`.
Surfaced in the dashboard's **Second Thoughts** tab (roadmap #15): warmed/cooled cards pairing his
earliest vs. latest take, each quote deep-linking into the Raw Corpus via `deepLinkToCorpus()`,
plus a direction filter — injected via `build_dashboard`'s `/*__CONTRADICTIONS_DATA__*/` placeholder
with an empty-board stub in CI / fresh clones (prompting `make contradictions`). No conductor/network.
Like `entity_graph`/`entity_stance`, subjects are **canonicalized** through `entity_aliases.py`
(`--no-aliases` opts out), so one mind-change is a single row rather than one per spelling. Because
mention-matching is case-*sensitive* here (a proper-noun guard: "Jack" the person vs. "jack up"),
evidence is gathered under **every** raw spelling in a group and then de-duplicated on
`(slug, sentence)` — which also keeps the corpus's 23 duplicate slugs (see `scraper/README.md`) from
counting the same sentence twice. (Roadmap #15 × #14.)

`anthology.py` — a family keepsake, outside the default chain; run via `make anthology` (HTML +
JSON) or `make anthology-pdf` (adds the PDF). Pure/offline: reads `themes.json` + `predictions.json`
and assembles a "best of" — his vindicated **best calls** (most-committed first) and a **signature
piece** per dominant theme — rendered as a print-ready Georgia-serif HTML document with `@media print`
page breaks. `make anthology-pdf` turns that HTML into `anthology.pdf` via the `render_pdf(html, pdf)`
helper, whose default seam is headless Chromium (Playwright, already a dev dep); the browser call is
isolated behind that injectable seam so all orchestration stays offline-unit-tested (the same pattern
as `rag_eval`/`voice_eval`/`embedding_compare`), and it degrades to a clear `SKIP PDF` (leaving the
interim print-ready HTML) when no browser is present. The rendered `anthology.html`/`anthology.pdf`
are **git-ignored** build outputs (regenerate on demand). No conductor/network. (Roadmap #24.)

### Track Record: from advisory guess to family ruling

`predictions.py` deliberately leaves every prediction's `status` at `pending` — an LLM's
recollection is not a ruling on how Dad's bets turned out. Two modules layer verdicts on top of
it, and both write back into `predictions.json`.

`verdict_backfill.py` — **owner-gated and paid**; run via `make backfill-verdicts`. For each
prediction it gathers external evidence (a web search) and asks a T3 model to rule *with the
sources it relied on*, landing `evidence_*` fields (verdict, rationale, normalized source list)
so the family can see the receipts. Because it spends real money it preflights the conductor and
refuses to start when it's down. (Plan 0004 step 1, roadmap #11.)

`adjudicate.py` — the **human-override layer**; run via `make adjudicate` for a resumable
review loop over the unadjudicated predictions, writing `human_verdict` plus a free-text note.
Effective-verdict precedence is `human_verdict` > `evidence_verdict` > `llm_verdict` > `status`
> `pending`: an evidence-grounded ruling outranks an ungrounded one, and **a family ruling
always wins**. `--report` additionally emits the confidence **calibration** view — hit-rate
bucketed by his hedging language, plus "most right / most wrong" conviction boards (roadmap
#12). Its stdout *is* the product here (an interactive review loop), so this module keeps its
`print`s by design. Pure/offline.

### Family keepsakes

`reading_room.py` — the builder behind the dashboard's **Reading Room** tab (roadmap #21).
Joins `themes.json` (per-article theme label) and the manifest (ordering, word counts) to the
full bodies in `data/raw/*.json`, emitting `reading_room.json`: every column with its
paragraphs, reading time, theme tag, prev/next links and a "read on Forbes" deep link. Because
it embeds **full article text** it is **git-ignored** — regenerate on demand. Note there is **no
`make` target**; run `python -m analysis.reading_room`. Deterministic and offline.

`year_in_review.py` — the annual counterpart to On This Day (roadmap #23); run via
`make year-in-review` (`ARGS="--year 2024"`; defaults to the last complete year). Reads
`themes.json`, `predictions.json` and the corpus and renders one keepsake email to
`data/cron/emails/` in the same Georgia-serif voice as the weekly note: how much he wrote, the
themes that dominated, and his most notable calls. **No conductor, network, or LLM** — safe
unattended. Delivery stays human-in-the-loop through the same Gmail-MCP draft path.

`delivery.py` — the reusable, side-effect-free half of On This Day delivery (plan 0003 /
decision **D9**): parses the git-ignored recipient list and assembles a dry-run summary that
**sends nothing**. `bin/create_gmail_draft.py` is built on it, and `make send-on-this-day` is
the owner's approval gate. Actual draft creation happens through the Gmail MCP in a Claude
session, never from here — so no mail credentials are ever stored.

### Evaluation harnesses & the Geo-LLM ladder

These establish whether Ask Dad is *trustworthy* and whether a fine-tune would beat it
(roadmap #25/#26, plans 0007/0008). All follow the same shape: the one networked seam is
**injected**, so the scoring math is pure and TDD'd offline, and the live CLI is owner-gated on
conductor reachability.

`rag_eval.py` — **RAG faithfulness** baseline; `make rag-eval`. Mirrors production exactly
(`semantic_search.search()` → answer only from retrieved snippets, cite by `title (year)`,
abstain with "I haven't written about that specifically"), then judges each answer for
citation accuracy, hallucination and correct abstention over the committed
`eval/questions.json`. Writes `data/analysis/rag_eval.json` — the bar any fine-tune must beat.

`voice_eval.py` — **voice fidelity**; `make voice-eval`. Blind A/B/C ranking: candidate
passages (`real` excerpt / `rag` answer / `finetuned` answer) are anonymized to labels with a
seeded, reproducible shuffle, ranked by a judge model on how much they read like Calhoun, then
un-blinded into win-rates, average ranks and a `finetuned_over_rag` head-to-head. Also computes
offline **style metrics** against his distinctive words (`--style-only` needs no judge).

`voice_trials.py` — deterministic input builder for the above; `make voice-trials`. Turns 26a's
held-out split (`data/training/heldout.jsonl`) into a real `eval/voice_trials.json` skeleton —
each trial's prompt plus a length-balanced genuine excerpt, with `rag`/`finetuned` left as
paste-here placeholders. **Leakage-free by construction** (prompts come from the held-out
split). The output embeds real bodies, so it is git-ignored; the hand-authored
`eval/voice_trials.example.json` template is committed.

`geo_baseline.py` — freezes the pre-fine-tune numbers (plan 0008 step 26b). Reads the already
written `rag_eval.json` and curates it into `geo_llm_baseline.json` plus a short markdown note,
with a `voice` slot left pending for 26d. Makes **no** conductor calls of its own; if
`rag_eval.json` is absent it tells the owner to run `make rag-eval` and exits without writing.
Module CLI only (`python -m analysis.geo_baseline`).

`geo_llm_status.py` — assembles `data/analysis/geo_llm.json`, the snapshot behind the
dashboard's **Geo-LLM** tab: dataset stats, a sample training pair, the RAG/voice summaries,
the 26a–26f pipeline checklist, and any fine-tune registration marker. Called **directly by
`viz/build_dashboard.py`** during the dashboard build rather than from a `make` target, and
every field degrades to a safe default when its source file is missing — so the build never
breaks mid-experiment.

## 3. The conductor (LLM abstraction)

All model calls go to a **local OpenAI-compatible server** at `http://127.0.0.1:8080/v1`
(sibling repo `/Volumes/FamilyWorkDrive/development/local-llm-conductor` — not in this repo).
Code uses the `openai` Python SDK (or `fetch` from the browser) pointed at that base URL.

- **Chat:** `client.chat.completions.create(model="auto", messages=[...],
  extra_body={"tier": 2|3, "function": "text"})`. The conductor picks the actual model and
  injects `conductor.model_used` into the response.
- **Embeddings:** `client.embeddings.create(model="sbert-mpnet-v2", input=texts)`. The
  embedding model is **pinned** — vector spaces aren't comparable across models, so search,
  Ask Dad, and On This Day must all use the same one.
- **Tiers:** T1 `phi3:mini` (query expansion, ~free), T2 local reasoning model (free,
  default), T3 OpenRouter (paid; selected with `--remote` or the dashboard tier toggle).

No API keys in this repo; T3's `OPENROUTER_API_KEY` lives in the conductor's own `.env`.

**Preflight** (`analysis/conductor.py`, roadmap #6) — the single home for "is it up, and what
do I say if it isn't", replacing three byte-for-byte copies of `_conductor_up()`. `conductor_up()`
GETs `/models` (cheap — no model load) and treats any connection error or non-200 as down;
`require_conductor()` is what the owner-gated CLIs (`rag_eval`, `voice_eval`, `verdict_backfill`,
`embedding_compare`) call to abort with **exit 2** and one clear message before spending a paid
T3 request. The network call sits behind an injectable `opener`, so callers test the gating
offline. `make conductor-check` runs it standalone.

> Full reference (exact signatures, return shapes, error/retry behavior, health check):
> [`conductor-contract.md`](conductor-contract.md).

## 4. Presentation

### Dashboard (`viz/build_dashboard.py` + `dashboard/template.html`)

`build_dashboard.py` is a **template injector**: it replaces `/*__*_DATA__*/` placeholders in
`template.html` with the analysis JSON (themes, psychoprofile, linguistics, manifest,
entities, embeddings, predictions) and writes `dashboard/index.html`. Missing inputs degrade
to empty stubs. The dashboard is **fully client-side** — vanilla JS + D3 v7 from CDN, no
build step, no backend. The only runtime calls are browser → conductor (for Ask Dad +
search embeddings). **Sixteen tabs:** Theme Map, Timeline, Psychoprofile, Linguistic DNA,
Influence Map, Raw Corpus, Semantic Search, **Ask Dad**, **Track Record**, Network,
Stance, Intellectual Arc, Calhoun-isms, Second Thoughts, Reading Room, Geo-LLM. The nav
`flex-wrap`s so added tabs can't overflow the row.

Tabs whose artifact is git-ignored for licensing (Reading Room, Calhoun-isms, Second Thoughts)
inline an **empty stub** on CI and fresh clones, and render a prompt naming the command that
builds them.

### Email (`analysis/on_this_day.py` + `bin/create_gmail_draft.py`)

On This Day writes an HTML email to disk; `create_gmail_draft.py` reads the latest one and
emits it for Claude Code's **Gmail MCP** to turn into a draft (no SMTP, no auto-send today).

## 5. Training (`training/prepare.py`)

Builds fine-tune inputs from the corpus: `finetune.jsonl` (raw text), `instruct.jsonl`
(quality-filtered chat format), `corpus.txt`, `metadata.csv`. Quality filter: word_count ≥
400 and TTR ≥ 0.3. `notebooks/finetune_qlora.ipynb` is the (WIP) QLoRA fine-tune.

## 6. Data layout

```
data/
  manifest.json              # master article index
  raw/{slug}.json            # one per article (gitignored — licensing)
  analysis/
    linguistics.json themes.json entities.json psychoprofile.json(.md) predictions.json
    embeddings.npy embeddings_meta.json embeddings.json   # (gitignored)
    runs.jsonl               # per-module run log + fingerprints + LLM cost
  training/                  # finetune.jsonl instruct.jsonl corpus.txt metadata.csv (gitignored)
  cron/
    weekly.log weekly_summary.jsonl launchd.{out,err}
    emails/on_this_day_*.html  on_this_day.jsonl
```

## 7. Automation & scheduling (macOS launchd)

- **Weekly** — `bin/com.calhoun.digitaldad-weekly.plist` → `bin/weekly_run.sh`, Sundays
  03:00. Conductor health check (clears stale WAL, restarts daemon), then `make scrape /
  analyze / dashboard / on-this-day`. Records worst exit code; never aborts the chain.
- **Daily product-dev agent** — `scripts/launchd/com.calhoun.digitaldad-daily.plist` →
  staged trampoline → headless Claude (opus-4.8/high) running
  `scripts/daily_routine_prompt.md`, 01:00 daily. Produces one draft PR; never merges.

Because the repo lives on an **external volume**, the daily agent uses a trampoline staged
on the system disk and requires a one-time **Full Disk Access** grant for `/bin/bash`.
