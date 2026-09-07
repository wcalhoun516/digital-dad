# Plan 0009 — Give the Geo-LLM fine-tune a fair test

## Goal

The QLoRA fine-tune behind **D15** was trained on a dataset that could not fit through the
window. Reshape the training data so 100% of the corpus reaches the model, make the existing
preflight able to *block* a truncating run instead of merely mentioning it, then retrain and
re-measure against D15's numbers.

Roadmap **#39** (passage-level records) + **#40** (retrain and re-measure). Design:
[`superpowers/specs/2026-09-07-next-phase-design.md`](../../superpowers/specs/2026-09-07-next-phase-design.md).

This is the highest-leverage change available in this repo, and it needs no new source
material, no new dependency, and no network.

## Context — the defect, measured

`training/prepare.py::build_instruct_record` emits **one record per article**: prompt
`"Write an analysis of <title>"`, completion = the entire article body.
`training/finetune_config.py::QLoRAConfig.max_seq_len` is **1024**.

The repo's own `make finetune-preflight` already reports this today:

```
QLoRA fine-tune preflight — FAIL
  base_model: microsoft/Phi-3-mini-4k-instruct  max_seq_len: 1024
  split: train=138  heldout/valid=34
  [PASS] chat shape: 172/172 well-formed
  [PASS] split disjoint: 0 leaked record(s)
  [FAIL] length budget: 172/172 (100.0%) over max_seq_len=1024
        (est tokens median=3041 max=5319, ~4 chars/token)
        → set max_seq_len≈8192 (covers ~95% — P95 est 4354 tokens) or chunk article
          bodies, else these records are dropped/truncated by mlx-lm.
```

**It exits 0 by design** ("report-only so it never turns `make verify` red"), so nothing has
ever blocked on it, and D15 was written without acting on it.

Independent measurement on the shipped `data/training/train.jsonl`: 138 records, assistant
completions median ~11,811 chars ≈ 2,952 tokens, **138/138 over budget**, ~141,312 of ~416,304
tokens retained — **33%**. Everything the model saw was an article *opening*: epigraph quotes,
datelines, thesis paragraphs. It never saw a conclusion or a sustained argument.

D15's style metrics are the fingerprint of exactly that: TTR 0.35 vs a real-corpus 0.70
(openings are formulaic across articles) and ~2× over-use of hinge words ("Notably",
"Crucially") that cluster in openings. **D15's verdict is not being reversed here — it is being
re-tested on data that fits.** Its stated revival path (more examples, more iters, higher rank)
is superseded: the defect is example *shape*, not count.

Existing pieces to reuse — do not reinvent:

- `analysis/utils.chunk_text` — the corpus chunker Ask Dad retrieval already uses.
- `training/finetune_preflight.py` — `check_length_budget`, `check_split_disjoint`,
  `chat_shape_errors` all exist and are tested.
- `scraper/manifest_check.py` — the established `--strict` (exit 1) precedent for a
  report-only tool that gains an enforcing mode.
- `training/prepare.py::split_articles` / `eval_grounded_slugs` — the article-level split that
  keeps #25's RAG-eval articles out of training. **It is currently correct and must stay
  correct.**

## Steps — each step is its own PR

Use `superpowers:test-driven-development` throughout; every step here is pure, offline and
unattended-safe except step 4, which is owner-interactive compute.

1. **Passage-level records (S).** Add chunked record generation to `training/prepare.py`:
   split article bodies on **paragraph boundaries** via `analysis.utils.chunk_text` into
   complete records that fit `max_seq_len` with headroom for the system + user turns. Vary the
   task shape — continue-this-passage, write-on-this-topic, respond-to-this-claim — and record
   the shape in each record so evals can slice by it. Expect ~800–1,200 records from 204
   articles.
   **The trap to design against:** the held-out split must stay **article-level**. Every chunk
   of one article belongs to exactly one side of the split, or the voice eval leaks and its
   numbers become meaningless. TDD this specifically — a test that fails if any article's
   slug appears on both sides.
2. **Make the preflight enforceable (S).** Add `--strict` (exit 1 on FAIL) to
   `training/finetune_preflight.py`, mirroring `manifest_check.py`'s flag, and call it from the
   training path so a truncating dataset can never be trained on silently again. Default stays
   report-only so `make verify` is unaffected. Add a test that `--strict` exits 1 on the
   over-budget fixture and 0 on a well-formed one.
3. **Regenerate and report (S).** Run `make finetune-prep` + `make finetune-preflight` on the
   real corpus and paste the before/after into the PR: record count, token distribution,
   percentage over budget (must be **0%**), split integrity. **Do not commit
   `data/training/**`** — it is gitignored and stays that way.
4. **Retrain and re-measure vs D15 (M — owner-interactive).** Re-run the QLoRA on the reshaped
   set and `make voice-eval`, then record the delta against D15's baseline (fine-tune 0%
   win-rate, avg rank 2.88; RAG 1.50; real 1.63) and the style metrics (TTR 0.35 vs 0.70,
   hinge-word rate 101 vs 46 per 1k). Needs hours of local GPU and a paid T3 judge, so it is
   **not** unattended agent work — the agent should stop after step 3 and leave this plan in
   `ready/` for the owner.
5. **Record the outcome (S).** Write the result into `docs/decisions.md` as a new ADR that
   **supersedes D15's revival path** (not its verdict) — including the case where reshaped data
   still loses, which is a genuinely useful negative result and should be recorded as plainly
   as a win.

## Verification

- Step 1: TDD the chunking and the split. Non-negotiable assertions: no emitted record exceeds
  `max_seq_len`; no chunk splits mid-sentence; no article's slug appears in both train and
  heldout; the #25 RAG-eval articles remain excluded.
- Step 2: `--strict` exit codes proved red-green on fixtures.
- Step 3: `make finetune-preflight` prints **PASS** on the real regenerated data — that output
  pasted into the PR is the proof this plan worked.
- `make verify` green at every step; paste real output per §7.
- **Clear `__pycache__` before trusting any red→green proof** — this repo lives on an external
  volume and `pytest` has served a stale `.pyc` after an in-place rewrite.
- `superpowers:verification-before-completion` before flipping any PR to ready.

## Out of scope

- Raising `max_seq_len` as the primary fix. The preflight offers it as an alternative
  (≈8192), but on a 16GB M4 that trades hard against batch size and LoRA rank, and it yields
  *fewer* training examples rather than more. A modest bump (e.g. 2048) to reduce chunk
  fragmentation is a legitimate tuning knob for step 4 — replacing chunking with it is not.
- Ingesting new source material — that is plan 0010. This step must be measurable on the
  corpus that already exists, precisely so the ingest work can be judged against a working
  lever.
- Enabling the fine-tune in Ask Dad or any family-facing output. D15's `geo_llm_registration`
  marker stays undropped until step 4 says the fine-tune beats RAG.
