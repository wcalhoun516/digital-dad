# Plan 0001 — Verification infrastructure (lint + tests + `make verify`)

## Goal

Give the project a fast, reliable verification command. Today there is **no test or lint
setup at all**, which means the daily agent (and any contributor) has nothing to run in its
§7 fast-verification step. After this plan: `make verify` runs lint + tests + a dashboard
smoke build, and there's a `tests/` scaffold with real coverage of the pure-Python utilities.

This is the day-one hot-path task on purpose: it's low-risk, self-contained, and every future
daily run depends on the command it creates. (Roadmap items #1–#3.)

## Context

- Stack: Python ≥3.12, dependencies via `pyproject.toml` optional-extras, interpreter at
  `.venv/bin/python`. Build orchestrated by `Makefile`.
- Good first test targets are pure functions with no network/LLM dependency:
  - `scraper/utils.py`: `slugify()`, `is_article_url()` (and the retry/rate-limit helpers).
  - `analysis/utils.py`: `clean_text()` (strips Forbes boilerplate), `chunk_text()`.
  - The corpus-fingerprint helper in `analysis/__main__.py`.
- Do **not** write tests that require the conductor, network, or a populated `data/raw/`.

## Steps (use TDD — `superpowers:test-driven-development`)

1. **Add dev dependencies.** In `pyproject.toml`, add a `[project.optional-dependencies]`
   `dev = ["pytest>=8", "ruff>=0.6"]` group (and fold into the `all` extra). Add a `[tool.ruff]`
   section: target py312, a sensible line length (match the existing code — ~100), enable
   `E,F,I` to start (don't mass-reformat the repo in this PR — keep the diff small).
2. **Create `tests/`** with `tests/__init__.py` and `tests/conftest.py` (add repo root to
   path if needed). Write `tests/test_scraper_utils.py` and `tests/test_analysis_utils.py`:
   - `slugify`: spaces/punctuation/case → safe slug; idempotent; unicode.
   - `is_article_url`: accepts `/sites/georgecalhoun/...`; rejects `/amp/`, pagination, other authors.
   - `clean_text`: removes a known boilerplate fragment, preserves body.
   - `chunk_text`: respects size, doesn't drop content, splits on sentence boundaries.
   Write each test first, watch it fail, then confirm against the real implementation
   (these functions already exist — the tests pin current behavior).
3. **Add Makefile targets:**
   - `test:` → `$(PYTHON) -m pytest -q`
   - `lint:` → `$(PYTHON) -m ruff check .`
   - `fmt:`  → `$(PYTHON) -m ruff format .`
   - `verify:` → `lint test` then `$(MAKE) dashboard` as a smoke build (verify it still emits
     `dashboard/index.html` without error). Keep `verify` fast (< ~1 min).
4. **Install + run:** `.venv/bin/pip install -e ".[dev]"`, then `make verify`. Fix only what's
   needed to make the new tests + lint pass on the files you touched. If ruff flags large
   swaths of pre-existing code, scope the lint to passing cleanly (e.g. start with the new
   `tests/` + touched files) rather than reformatting the whole repo here.

## Verification

- `make test` → green, with the new tests actually exercising the utils.
- `make lint` → clean (at least on new/touched files).
- `make verify` → completes and `dashboard/index.html` is regenerated.
- Use `superpowers:verification-before-completion` before flipping the PR to ready: paste the
  real command output into the PR's `## Verification` section.

## Out of scope (leave for later roadmap items)

- GitHub Actions CI (#4), pre-commit hooks (#5), repo-wide reformatting, conductor preflight
  refactor (#6), structured logging (#7).
