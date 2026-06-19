PYTHON := .venv/bin/python

# Lint/format are scoped to tests/ for now: the existing modules carry pre-existing
# ruff findings (broadening the scope is a follow-up roadmap item, #1-3/cleanup).
LINT_PATHS := tests

.PHONY: scrape manifest-check analyze training dashboard all serve search on-this-day send-on-this-day adjudicate backfill-verdicts rag-eval voice-eval voice-trials clean test lint fmt verify verify-responsive

scrape:
	$(PYTHON) -m scraper $(ARGS)

# Audit data/manifest.json against data/raw/*.json: duplicate slugs/urls/content_hash,
# missing content_hash, and manifest/disk drift. Report-only by default (exit 0); pass
# ARGS=--strict to exit non-zero on issues (for CI), or ARGS=--json for machine output.
manifest-check:
	$(PYTHON) -m scraper.manifest_check $(ARGS)

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

search:
	$(PYTHON) -m analysis.semantic_search "$(QUERY)"

on-this-day:
	$(PYTHON) -c "from analysis.on_this_day import run; run()"

# Approval gate: prints who/what the latest email would go to (sends nothing).
# After reviewing, create the Gmail draft via the Gmail MCP in Claude Code.
send-on-this-day:
	$(PYTHON) bin/create_gmail_draft.py --dry-run

# Interactive: walk pending predictions, confirm/override the advisory LLM verdict.
# Human verdicts win and are written back after each ruling (resumable). ARGS e.g. --limit 20.
adjudicate:
	$(PYTHON) -m analysis.adjudicate $(ARGS)

# Owner-gated: evidence-augmented verdict backfill. Makes paid T3 calls and refuses to run
# if the conductor is down, so run it deliberately (NOT from automation). Resumable +
# incremental. ARGS e.g. --limit 20 or --evidence-file evidence.json. Adjudicate afterwards.
backfill-verdicts:
	$(PYTHON) -m analysis.verdict_backfill $(ARGS)

# RAG faithfulness eval baseline for Ask Dad (plan 0007). Owner-gated: the generation +
# judge passes make conductor calls (judge defaults to paid T3), so it refuses to run if
# the conductor is down. Writes data/analysis/rag_eval.json. ARGS e.g. --limit 5 or
# --judge-tier 2. Run deliberately (NOT from automation).
rag-eval:
	$(PYTHON) -m analysis.rag_eval $(ARGS)

# Voice-fidelity blind-A/B eval for the Geo-LLM fine-tune (plan 0008 step 26d). Owner-gated:
# the judge pass makes conductor calls (defaults to paid T3), so it refuses to run if the
# conductor is down. Reads eval/voice_trials.json (owner-produced once 26c's adapter exists),
# writes data/analysis/voice_eval.json. ARGS e.g. --judge-tier 2. Run deliberately (NOT from
# automation).
voice-eval:
	$(PYTHON) -m analysis.voice_eval $(ARGS)

# Build the eval/voice_trials.json skeleton for 26d from 26a's held-out split (plan 0008).
# Pure/offline (no conductor, no paid calls): fills each held-out prompt + a `real` excerpt,
# leaving `rag`/`finetuned` as placeholders for the owner to paste. The output embeds real
# article bodies and is gitignored. ARGS e.g. --limit 10 or --seed 42.
voice-trials:
	$(PYTHON) -m analysis.voice_trials $(ARGS)

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check $(LINT_PATHS)

fmt:
	$(PYTHON) -m ruff format $(LINT_PATHS)

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
