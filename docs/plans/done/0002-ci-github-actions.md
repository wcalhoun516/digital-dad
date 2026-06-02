# Plan 0002 — CI: GitHub Actions running `make verify` on PRs

## Goal

Every PR to `main` automatically runs lint + tests, so the daily agent's unattended PRs
show a green/red check before a human reviews them. This is the second foundation piece —
it only makes sense once `0001` has created `make verify` / `make lint` / `make test`.

## Context

- Depends on **0001** (lint + tests + `make verify`). If `0001` hasn't merged yet, base this
  work on top of it or note the dependency in the PR.
- Stack: Python ≥3.12, deps via `pyproject.toml` optional extras; dev tools in the `dev`
  extra that 0001 adds.
- **CI must not require the conductor, network, or scraped data.** The dashboard build
  degrades gracefully to empty stubs when `data/analysis/*` is absent (see
  `viz/build_dashboard.py`), so a smoke build is safe, but the *tests* should already avoid
  network/LLM per 0001.

## Steps

1. Create `.github/workflows/verify.yml`:
   - Trigger: `pull_request` (to `main`) and `push` to `main`.
   - Single job on `ubuntu-latest`, Python 3.12 via `actions/setup-python`.
   - Cache pip. `pip install -e ".[dev]"`.
   - Run `make lint` then `make test`. (Leave the `make dashboard` smoke step out of CI if it
     pulls heavy deps like spaCy models; keep CI fast — lint + tests are the gate.)
2. Make the workflow resilient: if `make` targets don't exist yet (0001 not merged), the job
   should fail loudly with a clear message rather than silently pass.
3. Add a CI status badge to `README.md` (top of the daily-agent section or near the title).

## Verification

- Open the draft PR; confirm the `verify` check appears and runs.
- Intentionally introduce a lint error in a scratch commit, confirm CI goes red, then revert.
- `superpowers:verification-before-completion`: paste the CI run URL + result into the PR's
  `## Verification` section before flipping to ready.

## Out of scope

- Pre-commit hooks (#5), matrix testing across Python versions, deploy/publish steps.
