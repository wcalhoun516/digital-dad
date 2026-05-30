PYTHON := .venv/bin/python

# Lint/format are scoped to tests/ for now: the existing modules carry pre-existing
# ruff findings (broadening the scope is a follow-up roadmap item, #1-3/cleanup).
LINT_PATHS := tests

.PHONY: scrape analyze training dashboard all serve search on-this-day clean test lint fmt verify

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

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check $(LINT_PATHS)

fmt:
	$(PYTHON) -m ruff format $(LINT_PATHS)

verify: lint test
	$(MAKE) dashboard

clean:
	rm -f data/raw/*.json
	rm -f data/analysis/*.json data/analysis/*.md
	rm -f data/training/finetune.jsonl data/training/corpus.txt data/training/metadata.csv
	rm -f dashboard/index.html
	rm -f data/manifest.json
