# Digital Dad

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
3. **Visualizes** it all in a self-contained interactive dashboard
4. **Prepares** the corpus for LLM fine-tuning

## Quick Start

```bash
# Clone and install
git clone https://github.com/wcalhoun516/digital-dad.git
cd digital-dad
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
playwright install chromium

# Set up your Anthropic API key (needed for psychoprofile analysis)
cp .env.example .env
# Edit .env with your key

# Run everything
make all

# Or run each step independently
make scrape      # Scrape Forbes articles
make analyze     # Run NLP + LLM analysis
make dashboard   # Build the interactive dashboard

# View the dashboard
make serve       # Opens http://localhost:8000
```

## Project Structure

```
scraper/        Web scraper with Playwright + BeautifulSoup + Wayback fallback
analysis/       NLP pipeline: themes, linguistics, psychoanalytic profile
viz/            Dashboard build script (injects data into HTML template)
dashboard/      Interactive visualization (D3.js, vanilla JS, no build step)
data/
  raw/          Individual article JSON files (gitignored)
  analysis/     Analysis outputs (themes, linguistics, psychoprofile)
  training/     Fine-tuning data: JSONL, plain text corpus, metadata CSV
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
- **Psychoanalytic author profile** — Claude analyzes the full corpus to surface
  dominant intellectual concerns, rhetorical patterns, emotional register, core
  values, and recurring fixations

## The Dashboard

A self-contained HTML file with five tabs:

- **Theme Map** — D3 force-directed bubble chart of articles by topic
- **Timeline** — Scrollable arc of an intellectual career
- **Psychoprofile** — Narrative report with radar chart
- **Linguistic DNA** — Histograms, bar charts, and trends
- **Raw Corpus** — Searchable table of every article

Open `dashboard/index.html` directly in a browser — no server required.

## Note on Data

Raw article files are gitignored to respect Forbes's content. Run `make scrape`
to populate them locally. Analysis outputs are tracked in the repo.

---

*Built with BeautifulSoup, Playwright, scikit-learn, the Anthropic API, and D3.js.*
