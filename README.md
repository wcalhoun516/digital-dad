# Digital Dad

[![verify](https://github.com/wcalhoun516/digital-dad/actions/workflows/verify.yml/badge.svg)](https://github.com/wcalhoun516/digital-dad/actions/workflows/verify.yml)

**Preserving a father's intellectual legacy.**

Dr. George Calhoun has spent years writing for Forbes — hundreds of articles on
telecommunications, technology policy, ESG, nuclear energy, and the forces that
shape our economic future. This project captures that body of work, analyzes it
with natural language processing and large language models, and presents it as an
interactive, explorable archive.

It is, at its core, a son's attempt to understand his father's mind through the
words he chose to share with the world.

---

## What This Does

1. **Scrapes** every Forbes article by Dr. George Calhoun into structured JSON
2. **Analyzes** the corpus: thematic clustering, linguistic fingerprinting, and
   an LLM-generated psychoanalytic author profile
3. **Lets you talk to the archive** — Ask Dad is a RAG chat where you ask a
   question and get an answer in his voice, grounded in the articles he wrote
4. **Tracks his predictions** — every falsifiable claim is extracted, dated, and
   audited against what actually happened
5. **Keeps the family connected** — a weekly email surfaces whichever article
   from the archive is most relevant to this week's news
6. **Visualizes** it all in a self-contained nine-tab interactive dashboard
7. **Prepares** the corpus for LLM fine-tuning

## Quick Start

```bash
# Clone and install
git clone https://github.com/wcalhoun516/digital-dad.git
cd digital-dad
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
playwright install chromium

# All LLM calls (psychoprofile, embeddings, Ask Dad, predictions)
# route through the local-llm-conductor service on port 8080:
#   curl http://127.0.0.1:8080/health
# No API keys are needed in this repo. T3 (--remote) needs OPENROUTER_API_KEY
# set in the conductor's own .env, not here.

# Run everything (uses T2 local LLM by default, free)
make all

# Or run each step independently
make scrape                              # Scrape Forbes articles
make analyze                             # Run NLP + LLM analysis (T2 local)
make analyze ARGS="psychoprofile --remote"  # Use T3 remote (costs money)
make analyze ARGS="predictions"          # Extract falsifiable predictions + LLM verdicts
make dashboard                           # Build the interactive dashboard
make search QUERY="nuclear policy"       # Semantic search across the corpus
make on-this-day                         # Generate weekly "On This Day" email

# View the dashboard
make serve       # Opens http://localhost:8000
```

## Project Structure

```
scraper/        Web scraper with Playwright + BeautifulSoup + Wayback fallback
analysis/       NLP pipeline: themes, linguistics, psychoprofile, predictions, RAG, email
  predictions.py   Track Record — falsifiable prediction extraction + LLM verdicts
  on_this_day.py   Weekly email — matches news headlines to the archive
  semantic_search.py  Embeddings + RAG snippets for Ask Dad chat
viz/            Dashboard build script (injects data into HTML template)
dashboard/      Interactive visualization (D3.js, vanilla JS, no build step)
data/
  raw/          Individual article JSON files (gitignored)
  analysis/     Analysis outputs (themes, linguistics, psychoprofile, predictions)
  cron/emails/  Weekly "On This Day" email HTML files
  training/     Fine-tuning data: JSONL, plain text corpus, metadata CSV
bin/            Scripts: weekly cron, conductor restart, Gmail draft helper
```

## The Scraper

The scraper uses a three-tier strategy to handle Forbes's anti-bot protections:

1. **Playwright + stealth** for discovering article URLs via infinite scroll
2. **Requests + BeautifulSoup** for extracting individual article content
3. **Wayback Machine CDX API** as a reliable fallback

Articles are saved as JSON with title, date, body text, tags, and word count.

## The Analysis

- **Theme clustering** via TF-IDF + KMeans — groups articles by intellectual
  territory and tracks how topics evolve over time
- **Linguistic fingerprint** — sentence length distributions, vocabulary richness,
  readability scores, and the words that make his writing distinctively *his*
- **Psychoanalytic author profile** — a conductor-routed LLM (local Ollama by
  default, optionally a T3 remote model) analyzes the full corpus to surface
  dominant intellectual concerns, rhetorical patterns, emotional register, core
  values, and recurring fixations
- **Semantic search index** — every article is embedded via the conductor's
  `/v1/embeddings` endpoint (pinned to `sbert-mpnet-v2` for index consistency)
  and stored as a NumPy matrix for instant cosine similarity search
- **Track Record** — extracts every falsifiable prediction from the corpus via
  LLM, then runs an advisory verdict pass (vindicated / wrong / mixed / pending).
  The extraction is resumable: if the conductor crashes mid-run, rerunning picks
  up from where it left off (progress is checkpointed every 10 articles). Failed
  articles are skipped with a warning rather than aborting the whole run.
  The family can override any verdict by editing `data/analysis/predictions.json`
- **"On This Day" email** — matches this week's news headlines against the corpus
  by cosine similarity, generates a 2-3 sentence intro in Dr. Calhoun's voice,
  and saves the email for delivery via Gmail draft

## Ask Dad — RAG Chat

The centerpiece interactive feature. Ask a question about any topic Dad has
written about and get an answer *in his voice*, grounded in his actual articles.

**How it works:**

1. Your question is expanded into focused search terms via phi3:mini (hybrid
   retrieval — both the raw query and the expanded version are embedded).
   The conductor then auto-swaps: unloads phi3:mini to free GPU memory.
2. Both versions are embedded via sbert-mpnet-v2 (in-process) and compared
   against the full corpus index via cosine similarity, merged by max score
   per article, and the top 8 are retrieved
3. A rich system prompt is built from the psychoprofile (intellectual dimensions,
   personality traits, rhetorical patterns) and the linguistic fingerprint
   (sentence length, em-dash frequency, vocabulary richness)
4. The conductor swaps again: unloads sbert, loads qwen2.5:14b (T2) or routes
   to Claude Sonnet (T3). The LLM streams a response with the retrieved article
   snippets as context, writing as Dr. Calhoun would — complete with his
   characteristic turns of phrase, his tendency to frame arguments historically,
   and his fondness for the well-placed em dash
5. Each answer footnotes its source articles with titles and dates

**Tier toggle:** The dashboard offers T2 (local, free, qwen2.5:14b) or T3
(Claude Sonnet via OpenRouter, ~$0.01–0.03/query). T3 produces noticeably
better persona adherence. The actual cost from the OpenRouter response is
displayed after each query.

```bash
# Requires conductor running on port 8080
# Open dashboard → Ask Dad tab, or use the conductor API directly
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What does Dad think about nuclear energy?"}],
       "stream":true, "tier":2, "function":"text"}'
```

## The Calhoun Track Record — Prediction Tracker

Extracts every falsifiable prediction Dr. Calhoun made across his entire corpus,
dates them, categorizes them by topic and confidence level, and runs an LLM
verdict pass to assess whether each one was vindicated, wrong, mixed, or still
pending.

**How it works:**

1. Each article is sent through the conductor (T3 recommended for quality) with
   a prompt that extracts predictions, the date they were made, the target
   horizon, and Dr. Calhoun's confidence language ("hedged" / "confident" /
   "certain")
2. A second LLM pass audits each prediction against real-world outcomes, using
   the model's knowledge of what actually happened after the prediction date
3. LLM verdicts are clearly labeled as advisory (`verdict_source: "llm"`) —
   the family can override any verdict by editing `predictions.json` directly
   and changing `verdict_source` to `"manual"`

**Resilience:** The extraction is resumable — progress is checkpointed every 10
articles, failed articles are skipped rather than aborting, and API calls retry
up to 3 times with backoff. A crashed conductor won't lose work; just restart
and rerun.

```bash
# Extract predictions (T2 local, free but slower/lower quality)
make analyze ARGS="predictions"

# Extract via T3 (Claude Sonnet, better quality, costs money)
make analyze ARGS="predictions --remote"

# Dashboard → Track Record tab for interactive browsing
# Filter by topic, verdict, confidence level
```

**Dashboard tab:** Filterable cards showing each prediction with its date,
source article, topic, confidence language, and LLM verdict with reasoning.
Aggregate stats show the breakdown by verdict, topic, and year.

## "On This Day" Weekly Email

Every Sunday, the weekly cron picks the most thematically relevant article from
the archive given the week's news, writes a 2–3 sentence intro in Dr. Calhoun's
voice, and saves it as an HTML email.

**How it works:**

1. Fetches headlines from Reuters (business, tech) and NYT (business) via RSS
2. Embeds each headline via the conductor's sbert-mpnet-v2 endpoint
3. Finds the corpus article with the highest cosine similarity to any headline
4. Generates a 2–3 sentence intro via the conductor T2 LLM, written as
   Dr. Calhoun introducing his own article in the context of this week's news
5. Saves the email HTML to `data/cron/emails/on_this_day_YYYY-MM-DD.html`
6. Logs results to `data/cron/on_this_day.jsonl`

```bash
# Generate manually
make on-this-day

# Create a Gmail draft (via Claude Code with Gmail MCP)
python bin/create_gmail_draft.py
```

The email turns the static archive into a living thing — once a week, the family
gets a small artifact: dad explaining the present through something he wrote in
the past.

## The Dashboard

A self-contained HTML file (`dashboard/index.html`) with nine tabs:

| Tab | Description | Requires Conductor? |
|---|---|---|
| Theme Map | D3 force-directed bubble chart of articles by topic | No |
| Timeline | Scrollable arc of an intellectual career | No |
| Psychoprofile | Narrative report with radar chart | No |
| Linguistic DNA | Histograms, bar charts, and trends | No |
| Influence Map | Named entities extracted from the corpus | No |
| Raw Corpus | Searchable table of every article | No |
| Search | Semantic search via inlined embeddings + live query embedding | Yes |
| Ask Dad | RAG chat in Dr. Calhoun's voice (see above) | Yes |
| Track Record | Filterable prediction cards with LLM verdicts (see above) | No |

Open directly in a browser — no server or build step required for the static
tabs. Run `make serve` for `http://localhost:8000`.

The dashboard is built by `viz/build_dashboard.py`, which reads JSON analysis
outputs and injects them into `dashboard/template.html` at `/*__PLACEHOLDER__*/`
markers. Rebuild after any analysis change with `make dashboard`.

**Memory management:** The conductor automatically swaps Ollama models on the
16GB Mac mini — it tracks which model is loaded and preemptively unloads it
before loading a different one (e.g. phi3:mini for query expansion → unload →
sbert for embeddings → unload → qwen2.5:14b for the response). Consecutive
calls to the same model stay hot with no reload penalty. Heavy batch jobs
(like full prediction extraction) should still be run separately from Ask Dad
to avoid concurrent memory pressure.

## Conductor Dependency

All LLM and embedding calls route through the
[local-llm-conductor](../local-llm-conductor/) running at
`http://127.0.0.1:8080`. If the conductor is down, Ask Dad, Search, prediction
extraction, and On This Day will fail.

```bash
# Check if conductor is running
curl http://127.0.0.1:8080/health

# Restart it (kills stale processes, clears lock files, verifies health)
bash bin/conductor-restart.sh

# Or via launchd
sudo launchctl bootout system/com.calhoun.conductor
sudo launchctl bootstrap system /Library/LaunchDaemons/com.calhoun.conductor.plist
```

The conductor uses SQLite in DELETE journal mode (not WAL) for reliability on the
external drive, and automatically swaps Ollama models to stay within the 16GB
memory budget. The weekly cron (`bin/weekly_run.sh`) checks conductor health
before running analysis steps and restarts it if needed.

## Note on Data

Raw article files are gitignored to respect Forbes's content. Run `make scrape`
to populate them locally. Analysis outputs are tracked in the repo.

## Weekly auto-update

A launchd agent runs every Sunday at 03:00 to scrape any new articles, refresh
the analyses (modules with unchanged corpus fingerprints are skipped), rebuild
the embedding index, regenerate the dashboard, and generate the weekly "On This
Day" email.

```bash
# Install (idempotent — safe to re-run)
bin/install_weekly_cron.sh

# Run manually any time
bin/weekly_run.sh

# Check next scheduled run / state
launchctl print "gui/$(id -u)/com.calhoun.digitaldad-weekly" | grep -E "next|state"

# Uninstall
launchctl bootout "gui/$(id -u)/com.calhoun.digitaldad-weekly"
```

Logs land in `data/cron/weekly.log` and a structured one-line-per-run summary
goes to `data/cron/weekly_summary.jsonl`. macOS launchd reschedules missed runs
on the next wake, so the Mac mini being asleep at 3am is fine.

---

## Daily product-dev agent

Separate from the weekly *data* refresh above, a second launchd job improves the
*product* itself. Every day at **01:00** it runs Claude headlessly against a
strict playbook ([`scripts/daily_routine_prompt.md`](scripts/daily_routine_prompt.md))
and opens **one small, reviewable draft PR** on a `daily/*` branch. It never
merges and never pushes to `main` — you review during the day and merge what you
like. It picks work in priority order: pre-baked plans in
[`docs/plans/ready/`](docs/plans/ready/) → pins in
[`docs/daily-log.md`](docs/daily-log.md) → the [roadmap](docs/roadmap.md).

```bash
# Install (idempotent). Repo is on an external volume, so this also prints the
# one-time Full Disk Access grant you must give /bin/bash.
scripts/launchd/install_launchd.sh

# Safe verification — runs all preflight but opens NO PR
DAILY_ROUTINE_DRY_RUN=1 bash "$HOME/digital-dad-launchers/daily_routine.sh"

# Check next scheduled run / fire a real run now (opens a draft PR) / uninstall
launchctl print     "gui/$(id -u)/com.calhoun.digitaldad-daily" | grep -E "next|state"
launchctl kickstart -k "gui/$(id -u)/com.calhoun.digitaldad-daily"
scripts/launchd/uninstall_launchd.sh
```

**How it chooses work**, each run, in strict order:

1. **Resume** any in-progress `daily/*` PR newer than 3 days (so a PR can deepen over a
   couple of days before you review it).
2. **Pre-baked plans** — the oldest `NNNN-*.md` in [`docs/plans/ready/`](docs/plans/ready/).
3. **Your pins** — the first unchecked `[ ]` under `## User pins` in
   [`docs/daily-log.md`](docs/daily-log.md).
4. **Roadmap** — the least-recently-worked category in [`docs/roadmap.md`](docs/roadmap.md).

**Current queue (next ~2 weeks)** — foundation first, then the family-facing must-haves
(full detail in [`docs/roadmap.md`](docs/roadmap.md#-planned-execution-order-next-2-weeks)):

1. Verification infra (tests + ruff + `make verify`) → 2. CI on PRs →
3. On This Day reaches the family → 4. Track Record scoreboard (verdicts + adjudication) →
5. Ask Dad persistence + citation links → 6. Mobile-friendly dashboard →
7. RAG faithfulness eval. After that it favors family/emotional-payoff items.

**Cadence:** review every couple of days — PRs deepen until you merge them. At 5 open
`daily/*` PRs it stands down until you clear the backlog.

**To steer it:** add a pin to [`docs/daily-log.md`](docs/daily-log.md) (beats the roadmap),
or drop a new `000N-*.md` plan into [`docs/plans/ready/`](docs/plans/ready/) (beats
everything). See [`docs/INDEX.md`](docs/INDEX.md) for the full documentation set.

---

*Built with BeautifulSoup, Playwright, scikit-learn, sentence-transformers, the local-llm-conductor, and D3.js.*
