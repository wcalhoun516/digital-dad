PYTHON := .venv/bin/python

# Lint/format are scoped to tests/ for now: the existing modules carry pre-existing
# ruff findings (broadening the scope is a follow-up roadmap item, #1-3/cleanup).
LINT_PATHS := tests

.PHONY: scrape analyze training dashboard all serve search on-this-day send-on-this-day adjudicate backfill-verdicts rag-eval clean test lint fmt verify verify-responsive

scrape:
	$(PYTHON) -m scraper $(ARGS)

analyze:
	$(PYTHON) -m analysis $(ARGS)

training:
	$(PYTHON) -m training

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
	rm -f dashboard/index.html
	rm -f data/manifest.json
