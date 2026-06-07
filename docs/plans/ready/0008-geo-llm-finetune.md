# Plan 0008 — "Geo LLM": fine-tune a George-Calhoun-voice model

## Goal

Run a series of **bite-size, individually-shippable experiments** toward a fine-tuned model
that writes in Dr. George Calhoun's voice ("Geo LLM"), and find out — with numbers — whether a
small local fine-tune beats the existing RAG ("Ask Dad") on **voice fidelity** without losing
**faithfulness**. Roadmap #26 (a–f). The whole effort is measured against the #25 RAG baseline
(plan 0007), which must land first.

This is deliberately sequenced as small slices so the daily agent can ship one reviewable PR at
a time on commodity hardware (Mac mini M4, 16GB), rather than one giant fine-tune PR.

## Context

- A starting notebook already exists: `notebooks/finetune_qlora.ipynb`. Data prep scaffolding
  is in `training/prepare.py` and the `training/` package.
- Corpus: 173 articles in `data/raw/*.json`; analysis outputs in `data/analysis/`.
- LLM access is via the **conductor** (`http://127.0.0.1:8080`): T1/T2 local, T3 remote judge.
  Embeddings pin `sbert-mpnet-v2`. (See `conductor.md` in the sibling repo.) **The conductor
  must be running** for the eval slices — if it is down, exit `blocked` per the routine.
- Hardware reality: 16GB unified memory. Favor small bases (≤3–7B) + QLoRA; this is an
  experiment in tractability as much as quality.
- **Prerequisite:** plan 0007 (RAG faithfulness eval) provides the baseline 26b compares to. If
  0007 has not landed, do its baseline-capture parts first or block on it.

## Steps — each step is its own PR

Use `superpowers:test-driven-development` for deterministic helpers (data shaping, metric math)
and `superpowers:verification-before-completion` before flipping any PR to ready.

1. **26a — Dataset builder (S).** Extend `training/prepare.py` to turn the corpus into
   instruction/chat pairs that elicit his voice (e.g. prompt → his-style passage), with a
   held-out split that does **not** overlap the #25 eval questions. Output
   `data/training/{train,heldout}.jsonl`. TDD the shaping/splitting logic on a small fixture.
2. **26b — Baseline capture (S).** Using the #25 harness, record the **pre-fine-tune** RAG
   numbers (voice + factuality) as `data/analysis/geo_llm_baseline.json` + a short markdown
   note. This is the bar to beat; no model training yet.
3. **26c — Smallest viable QLoRA (M).** Make `notebooks/finetune_qlora.ipynb` reproducible on a
   small local base (e.g. Qwen2.5-3B / Llama-3.2-3B): train an adapter on 26a's data, save it,
   and emit a handful of smoke generations. Goal is "tractable on the M4 + plausibly his voice,"
   not SOTA. Capture runtime/memory notes.
4. **26d — Voice-fidelity eval harness (M).** Reusable blind A/B: for held-out prompts, compare
   {RAG answer, fine-tuned answer, real excerpt} scored by a T3 judge through the conductor,
   plus a couple of cheap deterministic style metrics. Output a re-runnable report.
5. **26e — Register in the conductor (S).** Add the adapter/merged model to the conductor's
   `models.yaml` as a tier/function, and let Ask Dad answer via the fine-tune **behind a flag**
   (default off). Document the toggle.
6. **26f — Compare & decide (S).** Run 26d on the registered model; write the verdict
   (fine-tune vs RAG, with cost) into `docs/decisions.md`. This closes #26.

## Verification

- 26a: TDD the dataset shaping; eyeball a few generated pairs for voice plausibility.
- 26b/26d: harness runs end-to-end; spot-check a couple of judgments by hand; paste headline
  numbers into the PR.
- 26c: notebook runs top-to-bottom and produces an adapter; include sample generations + the
  runtime/memory footprint in the PR.
- 26e: conductor health-check passes and the flagged path returns a fine-tuned answer.
- Always `superpowers:verification-before-completion` before flipping to ready.

## Out of scope

- Large bases or multi-GPU training — this is the small-and-local experiment track.
- Changing the pinned embedding model (that's #27).
- Auto-enabling the fine-tune in Ask Dad by default — 26e is flagged/off until 26f decides.
