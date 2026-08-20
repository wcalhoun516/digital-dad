# Runbook: adding a new analysis module

How to add a module to the `analysis/` pipeline so it runs under `make analyze`, participates
in fingerprint-skipping, and (optionally) feeds the dashboard. Follow the existing conventions
— the goal is that the next module (e.g. roadmap #13–#17) looks like the ones already there.

Prereqs to read first: [`architecture.md` §2](../architecture.md) (the pipeline) and, if your
module calls a model, [`conductor-contract.md`](../conductor-contract.md).

---

## The shape of a module

Every analysis module is a file `analysis/<name>.py` that exposes a **`run(articles)`**
entry point, reads the corpus through the shared loader, and writes exactly one JSON artifact
to `data/analysis/<name>.json` via `save_analysis`. A deterministic (non-LLM) module looks
like this:

```python
"""<name>: one-line description of what this computes."""

from .utils import load_articles, clean_text, save_analysis


def run(articles: list[dict] | None = None) -> dict:
    if articles is None:
        articles = load_articles()

    result = {
        # ... your computed analysis ...
    }

    save_analysis("<name>.json", result)
    return result
```

Conventions that matter:

- **Accept `articles` as a parameter.** `analysis/__main__.py` loads the corpus once and passes
  it to every module — don't re-load inside `run()` when it's given. Defaulting to
  `load_articles()` keeps the module runnable standalone and testable.
- **Use the shared `utils` helpers** (`analysis/utils.py`) instead of re-implementing:
  - `load_articles()` → list of article dicts (sorted by date), read via `data/manifest.json`.
  - `load_manifest()` → the raw manifest (raises a clear error if `make scrape` hasn't run).
  - `clean_text(body)` → strips Forbes boilerplate + normalizes whitespace. Run article bodies
    through this before analysis.
  - `chunk_text(text, max_tokens, overlap)` → sentence-aware splitting for token budgets.
  - `save_analysis("<name>.json", data)` → writes pretty-printed UTF-8 JSON to
    `data/analysis/` and returns the path. **This is the only way to write your artifact** —
    it ensures the directory exists and a consistent format.
- **One module → one JSON output**, named after the module. (Embeddings is the exception: it
  writes `.npy` + meta + a flattened dashboard export.)
- **An article dict** has at least `slug`, `title`, `date`, `url`, `body`, `word_count`,
  `content_hash` (see the manifest schema in `architecture.md` §1).
- **If your module calls a model**, follow [`conductor-contract.md`](../conductor-contract.md):
  default to tier 2, guard the `openai` import, and never make an unguarded paid T3 call from
  code that could run unattended.

For a worked non-LLM example see `analysis/themes.py` (TF-IDF + KMeans → `themes.json`); for an
LLM example see `analysis/predictions.py` (tier-2 extraction, incremental/resumable saves).

---

## Wiring it into `make analyze`

`make analyze` is `python -m analysis`, dispatched by `analysis/__main__.py`. Three edits wire
a module in:

1. **Add the name to `ALL_MODULES`** (order matters — it's the run order):

   ```python
   ALL_MODULES = ["linguistic", "themes", "entities", "psychoprofile",
                  "semantic_search", "predictions", "<name>"]
   ```

   This also extends the CLI `choices`, so `python -m analysis <name>` works.

2. **Add a dispatch block** in `main()`, mirroring the existing ones. The `_should_run` /
   `_log_run` pair is what gives you fingerprint-skipping for free:

   ```python
   if "<name>" in modules:
       print("=" * 50)
       print("<NAME> — short description")
       print("=" * 50)
       if _should_run("<name>"):
           from .<name> import run as run_<name>
           run_<name>(articles)
           _log_run("<name>", fingerprint)
       print()
   ```

   Import inside the block (lazy import) so an optional heavy dependency doesn't slow down or
   break unrelated modules.

3. **Nothing else for the Makefile** — there's no per-module target. `make analyze` runs the
   whole chain; `make analyze <name>` (via `ARGS`) runs just yours. Only add a dedicated `make`
   target if the module has a *separate, deliberately-gated* entry point (as the eval modules
   do — see the owner-gated `rag-eval` / `voice-eval` targets).

### How fingerprint-skipping works (what you get for free)

`__main__.py` computes a corpus fingerprint — an MD5 over every article's `slug` +
`content_hash` (`_corpus_fingerprint`). Each completed module appends
`{timestamp, module, corpus_fingerprint}` to `data/analysis/runs.jsonl` via `_log_run`. On the
next run, `_should_run("<name>")` compares the current fingerprint to your module's last logged
one and **skips if unchanged** (unless `--force`). This is what makes the weekly cron cheap.

You participate simply by calling `_log_run(...)` after a successful `run()` in your dispatch
block — exactly as the snippet above does. (Modules that track LLM cost, like `psychoprofile`,
log their own richer line instead and are *not* `_log_run`'d by `__main__` — only do that if
you have cost data to record.)

---

## Surfacing it in the dashboard (optional)

The dashboard is a static template with data injected at build time by
`viz/build_dashboard.py` — no backend, no framework.

1. **Add a placeholder → file mapping** to `PLACEHOLDERS` in `viz/build_dashboard.py`:

   ```python
   "/*__<NAME>_DATA__*/": DATA_DIR / "analysis" / "<name>.json",
   ```

2. **Add a matching empty stub** to `_EMPTY_DEFAULTS` so the dashboard still builds before your
   module's first run (missing/invalid JSON degrades to the stub instead of breaking the
   build):

   ```python
   "/*__<NAME>_DATA__*/": '{"...": null}',
   ```

3. **Reference the placeholder in `dashboard/template.html`** — typically
   `const <NAME>_DATA = /*__<NAME>_DATA__*/;` inside a `<script>` — and render from it with
   vanilla JS / D3. `make dashboard` replaces the placeholder with your JSON and writes
   `dashboard/index.html`.

The injector validates each file is real JSON and falls back to the stub on a parse error, so a
malformed artifact can't take the whole dashboard down.

---

## Verify

There is no `make test` for `analysis` modules individually — write unit tests under `tests/`
(the suite is `make test` / `pytest -q`) and lean on `make verify`:

1. **Test the pure logic.** Put `test_<name>.py` in `tests/`, feed a small fixture of article
   dicts to `run(articles)` (or to your helper functions), and assert on the returned structure
   — don't depend on the real corpus. For model-calling code, inject a fake client/`chat` seam
   the way `rag_eval` / `voice_eval` do, so tests stay offline and free.
2. **Run the pipeline** once for real: `make analyze <name>` (conductor must be up if it makes
   model calls) and confirm `data/analysis/<name>.json` is written and well-formed
   (`python -m json.tool data/analysis/<name>.json`).
3. **`make verify`** (= `make lint` + `make test` + `make dashboard` smoke build) must stay
   green. If you added a dashboard placeholder, confirm the built `dashboard/index.html`
   contains your data (and still builds with the artifact absent — it should fall back to the
   stub).

Note: `make lint` is currently scoped to `tests/` only (existing modules carry pre-existing
ruff findings), so keep new test files clean.

---

## Document it (enforced)

Add an entry for your module to [`../architecture.md`](../architecture.md) §2 — what it reads,
what it writes, whether it's in the default `make analyze` chain, and whether the artifact is
committed or git-ignored. This is **not optional**:
`tests/test_docs_coverage.py` fails when a file in `analysis/` has no entry, because
`docs/INDEX.md` promises architecture.md is "the repo map ... read this before touching any
module" and eleven modules had quietly landed without one.

The guard looks for the **filename in a code span** — `` `<name>.py` `` or
`` `analysis/<name>.py` ``. Naming only the artifact it writes (`` `<name>.json` ``) does not
count: that's a mention, not a description, and it would let an undescribed module pass.

The same test checks the reverse direction for commands: any `` `make <target>` `` written in
a code span in the README, these docs, or `dashboard/template.html` must exist in the
`Makefile`. So if you add a target, reference it; if you reference one, add it — including in
`.PHONY`.

---

## Checklist

- [ ] `analysis/<name>.py` exposes `run(articles)`, uses `load_articles` / `clean_text` /
      `save_analysis`, writes `data/analysis/<name>.json`.
- [ ] Added to `ALL_MODULES` + a dispatch block in `analysis/__main__.py` with
      `_should_run` / `_log_run`.
- [ ] (If model calls) follows [`conductor-contract.md`](../conductor-contract.md): tier 2
      default, guarded import, no unguarded paid call in unattended paths.
- [ ] (If dashboard) placeholder in `PLACEHOLDERS` + `_EMPTY_DEFAULTS` + `template.html`.
- [ ] `tests/test_<name>.py` covers the logic offline; `make verify` green.
- [ ] Entry in [`../architecture.md`](../architecture.md) §2 naming `` `<name>.py` `` — enforced
      by `tests/test_docs_coverage.py`.
