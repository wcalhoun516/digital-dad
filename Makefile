PYTHON := .venv/bin/python

# Every top-level directory holding Python we ship. Keep this in lockstep with the
# pre-commit `files:` regex and with tests/test_lint_scope.py, which fails if a source
# package drops out of the gate. E501 is off for the source packages only (see pyproject).
LINT_PATHS := analysis scraper viz training tools bin tests

.PHONY: scrape manifest-check manifest-dedup coverage-audit ingest ingest-review analyze training dashboard all serve share search on-this-day send-on-this-day adjudicate backfill-verdicts entity-graph calhoun-isms contradictions rag-eval voice-eval voice-trials embedding-compare embedding-queries-check clean test lint fmt lint-json hooks verify verify-responsive

scrape:
	$(PYTHON) -m scraper $(ARGS)

# Audit data/manifest.json against data/raw/*.json: duplicate slugs/urls/content_hash,
# missing content_hash, and manifest/disk drift. Report-only by default (exit 0); pass
# ARGS=--strict to exit non-zero on issues (for CI), or ARGS=--json for machine output.
manifest-check:
	$(PYTHON) -m scraper.manifest_check $(ARGS)

# Collapse duplicate-slug entries in data/manifest.json (the de-dup fix manifest_check
# only reports; roadmap #8 follow-up). Report-only by default (exit 0, changes nothing);
# ARGS=--apply writes <manifest>.dedup.json, ARGS="--apply --in-place" rewrites it,
# ARGS="--apply --backfill-hashes" also fills missing content_hash from raw bodies.
manifest-dedup:
	$(PYTHON) -m scraper.manifest_dedup $(ARGS)

# Audit corpus coverage against the author's full Forbes footprint (roadmap #9): report
# articles we know exist (via Wayback CDX) but haven't scraped, plus the missing date ranges.
# Report-only by default (exit 0); ARGS=--strict exits non-zero on gaps, ARGS=--json for
# machine output, ARGS="--urls-file urls.txt" to audit against an offline URL list (no network).
coverage-audit:
	$(PYTHON) -m scraper.coverage_audit $(ARGS)

# Corpus II: extract everything in data/inbox/ into the review queue. Offline, and it
# never touches the corpus — `make ingest-review` is the only thing that does.
ingest:
	$(PYTHON) -m ingest $(ARGS)

# Review the staged queue and accept items into the corpus. This is the ONLY step that
# writes to the manifest. ARGS=--report for a read-only summary.
ingest-review:
	$(PYTHON) -m ingest.review $(ARGS)

analyze:
	$(PYTHON) -m analysis $(ARGS)

training:
	$(PYTHON) -m training

# Stage mlx-lm's train.jsonl/valid.jsonl in data/finetune_run/ from 26a's leakage-free
# split (plan 0008 step 26c). Offline + free; the actual QLoRA run lives in
# notebooks/finetune_qlora.ipynb. Run `make training` first to produce the split.
finetune-prep:
	$(PYTHON) -m training.finetune_config

# Preflight 26a's split against the QLoRA config before the 26c training run:
# chat-shape integrity, train/heldout disjointness, and sequence-length budget vs
# max_seq_len. Report-only (exit 0); add --strict for a non-zero gate.
finetune-preflight:
	$(PYTHON) -m training.finetune_preflight

dashboard:
	$(PYTHON) viz/build_dashboard.py

all: scrape analyze training dashboard

serve: dashboard
	@echo "Opening dashboard at http://localhost:8000"
	$(PYTHON) -m http.server 8000 -d dashboard

# Expose the dashboard to anyone, anywhere via one password-gated HTTPS link
# (Tailscale Funnel + bin/serve_dashboard.py). Installs a KeepAlive launchd
# service so it survives reboots. Re-run any time; --rotate-password to change pw.
share: dashboard
	bash scripts/launchd/install_dashboard.sh $(ARGS)

search:
	$(PYTHON) -m analysis.semantic_search "$(QUERY)"

on-this-day:
	$(PYTHON) -c "from analysis.on_this_day import run; run()"

# Approval gate: prints who/what the latest email would go to (sends nothing).
# After reviewing, create the Gmail draft via the Gmail MCP in Claude Code.
send-on-this-day:
	$(PYTHON) bin/create_gmail_draft.py --dry-run

# Annual "year in review" keepsake email (roadmap #23). Deterministic + offline (no conductor,
# no network): builds from data/analysis/{themes,predictions}.json and writes the HTML to
# data/cron/emails/. ARGS e.g. --year 2024 or --dry-run. Review then draft via the Gmail MCP.
year-in-review:
	$(PYTHON) -m analysis.year_in_review $(ARGS)

# Printable "best of" anthology keepsake (roadmap #24). Deterministic + offline (no conductor,
# no network): builds from data/analysis/{themes,predictions}.json and writes the print-ready
# data/analysis/anthology.html (+ anthology.json). ARGS e.g. --dry-run, --calls-limit 10.
anthology:
	$(PYTHON) -m analysis.anthology $(ARGS)

# As `anthology`, but also renders data/analysis/anthology.pdf from that HTML via headless
# Chromium (Playwright). Needs a browser, so it's a deliberate/local target (not automation):
# if Chromium is unavailable it prints SKIP PDF and still leaves the print-ready HTML.
anthology-pdf:
	$(PYTHON) -m analysis.anthology --pdf $(ARGS)

# Interactive: walk pending predictions, confirm/override the advisory LLM verdict.
# Human verdicts win and are written back after each ruling (resumable). ARGS e.g. --limit 20.
adjudicate:
	$(PYTHON) -m analysis.adjudicate $(ARGS)

# Owner-gated: evidence-augmented verdict backfill. Makes paid T3 calls and refuses to run
# if the conductor is down, so run it deliberately (NOT from automation). Resumable +
# incremental. ARGS e.g. --limit 20 or --evidence-file evidence.json. Adjudicate afterwards.
backfill-verdicts:
	$(PYTHON) -m analysis.verdict_backfill $(ARGS)

# Trace the "intellectual arc": year-over-year theme evolution derived from
# data/analysis/themes.json (run `make analyze` first). Pure/offline — no conductor,
# no network — so it's safe in automation. Writes data/analysis/intellectual_arc.json;
# ARGS=--dry-run prints the narrative without writing.
intellectual-arc:
	$(PYTHON) -m analysis.intellectual_arc $(ARGS)

# Entity co-occurrence graph (roadmap #14): who Dr. Calhoun writes about alongside whom,
# derived from data/analysis/entities.json (run `make analyze` first). Pure/offline — no
# conductor, no network — so it's safe in automation. Writes data/analysis/entity_graph.json;
# ARGS e.g. --dry-run, --top 60, --min-cooccur 3, or --no-exclude (keep byline/photo boilerplate).
entity-graph:
	$(PYTHON) -m analysis.entity_graph $(ARGS)

# Per-entity stance over time (roadmap #17): how his tone toward a person/org drifts by year,
# from data/analysis/entities.json + the corpus bodies (run `make analyze` first). Pure/offline
# heuristic (curated polarity lexicon; no conductor, no network) — safe in automation. Writes
# data/analysis/entity_stance.json. ARGS e.g. --dry-run, --top 40, --min-articles 4,
# --threshold 0.3, or --no-exclude (keep byline/photo boilerplate).
entity-stance:
	$(PYTHON) -m analysis.entity_stance $(ARGS)

# Contradiction / mind-change finder (roadmap #15): subjects (people/orgs) whose stance
# reversed sign between Dad's earlier and later writing, derived from data/analysis/entities.json
# + the corpus (run `make analyze` first). Pure/offline — no conductor, no network — so it's
# safe in automation. Writes data/analysis/contradictions.json; ARGS e.g. --dry-run,
# --min-mentions 6, --min-delta 1.5, --min-observations 6, or --no-exclude.
contradictions:
	$(PYTHON) -m analysis.contradictions $(ARGS)

# Calhoun-isms (roadmap #16): the most quotable/aphoristic sentences per theme, derived from
# data/analysis/themes.json + the corpus (run `make analyze` first). Pure/offline — no conductor,
# no network. Writes the git-ignored data/analysis/calhoun_isms.json (embeds body excerpts);
# surfaced in the dashboard's Calhoun-isms tab. ARGS e.g. --dry-run, --top 10, --min-score 2.
calhoun-isms:
	$(PYTHON) -m analysis.calhoun_isms $(ARGS)

# Reading Room (roadmap #21): the family's full-article reader, joining data/analysis/themes.json
# with the corpus bodies (run `make analyze` first). Pure/offline — no conductor, no network.
# Writes the git-ignored data/analysis/reading_room.json (embeds full bodies), surfaced in the
# dashboard's Reading Room tab — which is why the tab's empty state asks for this target.
# ARGS e.g. --dry-run or --limit 20.
reading-room:
	$(PYTHON) -m analysis.reading_room $(ARGS)

# RAG faithfulness eval baseline for Ask Dad (plan 0007). Owner-gated: the generation +
# judge passes make conductor calls (judge defaults to paid T3), so it refuses to run if
# the conductor is down. Writes data/analysis/rag_eval.json. ARGS e.g. --limit 5 or
# --judge-tier 2. Run deliberately (NOT from automation).
rag-eval:
	$(PYTHON) -m analysis.rag_eval $(ARGS)

# Embedding-model comparison before ever swapping the pinned sbert-mpnet-v2 (decision D2,
# roadmap #27). Owner-gated: a live pass embeds the corpus with each candidate model via the
# conductor, so it refuses to run if the conductor is down. Reads eval/embedding_queries.json,
# writes data/analysis/embedding_compare.json. ARGS e.g. --models nomic-embed-text bge-small
# --limit 40. Run deliberately (NOT from automation).
embedding-compare:
	$(PYTHON) -m analysis.embedding_compare $(ARGS)

# Offline validity check of the gold query set (eval/embedding_queries.json): every
# relevant_slug must resolve to a corpus article in data/manifest.json. No conductor /
# no embedding — safe to run anywhere (CI, fresh clone). Exit 1 on any problem.
embedding-queries-check:
	$(PYTHON) -m analysis.embedding_compare --check

# Voice-fidelity blind-A/B eval for the Geo-LLM fine-tune (plan 0008 step 26d). Owner-gated:
# the judge pass makes conductor calls (defaults to paid T3), so it refuses to run if the
# conductor is down. Reads eval/voice_trials.json (owner-produced once 26c's adapter exists),
# writes data/analysis/voice_eval.json. ARGS e.g. --judge-tier 2. Run deliberately (NOT from
# automation).
voice-eval:
	$(PYTHON) -m analysis.voice_eval $(ARGS)

# The deterministic half of the 26d voice eval, on its own: type-token ratio, sentence length
# and the Calhoun-"fingerprint" hit rate per source, with a delta vs `real`. Judge-independent —
# no conductor, no paid calls — so it gives a voice signal before any fine-tune exists and is
# safe to run unattended. Writes data/analysis/voice_style.json. ARGS e.g. --trials <path> or
# --fingerprint-words 40 (voice_eval takes no --limit).
voice-style:
	$(PYTHON) -m analysis.voice_eval --style-only $(ARGS)

# Build the eval/voice_trials.json skeleton for 26d from 26a's held-out split (plan 0008).
# Pure/offline (no conductor, no paid calls): fills each held-out prompt + a `real` excerpt,
# leaving `rag`/`finetuned` as placeholders for the owner to paste. The output embeds real
# article bodies and is gitignored. ARGS e.g. --limit 10 or --seed 42.
voice-trials:
	$(PYTHON) -m analysis.voice_trials $(ARGS)

# Preflight the local LLM conductor: exit 0 if it's reachable, 2 if not. The shared
# health check that every owner-gated eval (rag-eval, voice-eval, backfill-verdicts) uses
# before spending a paid T3 call. Run it first to confirm the conductor is up.
conductor-check:
	$(PYTHON) -m analysis.conductor $(ARGS)

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check $(LINT_PATHS)

fmt:
	$(PYTHON) -m ruff format $(LINT_PATHS)

# Validate the committed data/analysis/*.json artifacts parse as JSON (roadmap #5). This is
# the same check the pre-commit hook runs; report-only exit 0 unless a file is malformed.
lint-json:
	$(PYTHON) -m tools.check_analysis_json

# Install the git pre-commit hooks defined in .pre-commit-config.yaml (roadmap #5). One-time
# per clone; needs `pip install -e .[dev]` first so `pre-commit` is on PATH in .venv.
hooks:
	.venv/bin/pre-commit install

verify: lint test
	$(MAKE) dashboard

# Live both-breakpoint dashboard check (plan 0006 step 4). Needs a headless browser,
# so it is deliberately NOT part of `verify` (CI has no Chromium); it SKIPs cleanly when
# Chromium is unavailable. Build the dashboard first so it checks the real artifact.
verify-responsive: dashboard
	$(PYTHON) -m viz.verify_responsive

clean:
	rm -f data/raw/*.json
	rm -f data/analysis/*.json data/analysis/*.md
	rm -f data/training/finetune.jsonl data/training/corpus.txt data/training/metadata.csv
	rm -f data/training/instruct.jsonl data/training/train.jsonl data/training/heldout.jsonl
	rm -f docs/geo_llm_baseline.md
	rm -f dashboard/index.html
	rm -f data/manifest.json
