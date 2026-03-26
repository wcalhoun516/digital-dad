.PHONY: scrape analyze training dashboard all serve clean

scrape:
	python -m scraper $(ARGS)

analyze:
	python -m analysis $(ARGS)

training:
	python -m training

dashboard:
	python viz/build_dashboard.py

all: scrape analyze training dashboard

serve: dashboard
	@echo "Opening dashboard at http://localhost:8000"
	python -m http.server 8000 -d dashboard

clean:
	rm -f data/raw/*.json
	rm -f data/analysis/*.json data/analysis/*.md
	rm -f data/training/finetune.jsonl data/training/corpus.txt data/training/metadata.csv
	rm -f dashboard/index.html
	rm -f data/manifest.json
