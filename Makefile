PYTHON := .venv/bin/python

.PHONY: scrape analyze training dashboard all serve search on-this-day clean

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

clean:
	rm -f data/raw/*.json
	rm -f data/analysis/*.json data/analysis/*.md
	rm -f data/training/finetune.jsonl data/training/corpus.txt data/training/metadata.csv
	rm -f dashboard/index.html
	rm -f data/manifest.json
