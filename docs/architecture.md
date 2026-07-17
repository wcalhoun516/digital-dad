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

> Adding a module? See the runbook: [`runbooks/adding-an-analysis-module.md`](runbooks/adding-an-analysis-module.md).

`on_this_day.py` — not part of the default analyze chain; run via `make on-this-day`. Pulls
RSS headlines, embeds them, finds the best-matching archive article by cosine similarity,
generates a 2–3 sentence intro in Dr. Calhoun's voice (conductor T2), renders an HTML email
to `data/cron/emails/`, logs to `data/cron/on_this_day.jsonl`.

`entity_graph.py` — also outside the default chain; run via `make entity-graph`. A pure/offline
**derived** artifact: reads `entities.json`'s `per_article` lists and emits `entity_graph.json`,
an undirected co-occurrence graph (nodes = people/orgs, edge weight = shared-article count) for
a future dashboard network viz. Byline/photo-credit boilerplate is excluded by default
(`--no-exclude` to keep it). No conductor/network. (Roadmap #14.)

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

> Full reference (exact signatures, return shapes, error/retry behavior, health check):
> [`conductor-contract.md`](conductor-contract.md).

## 4. Presentation

### Dashboard (`viz/build_dashboard.py` + `dashboard/template.html`)

`build_dashboard.py` is a **template injector**: it replaces `/*__*_DATA__*/` placeholders in
`template.html` with the analysis JSON (themes, psychoprofile, linguistics, manifest,
entities, embeddings, predictions) and writes `dashboard/index.html`. Missing inputs degrade
to empty stubs. The dashboard is **fully client-side** — vanilla JS + D3 v7 from CDN, no
build step, no backend. The only runtime calls are browser → conductor (for Ask Dad +
search embeddings). Nine tabs: Theme Map, Timeline, Psychoprofile, Linguistic DNA, Influence
Map, Raw Corpus, Semantic Search, **Ask Dad**, **Track Record**.

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
