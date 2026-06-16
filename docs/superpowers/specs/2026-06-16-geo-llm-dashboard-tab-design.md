# Design — Geo-LLM dashboard tab ("living lab notebook")

**Date:** 2026-06-16
**Status:** approved (design), pending implementation plan
**Roadmap:** surfaces plan 0008 (#26a–f) progress in the family dashboard.

## Goal

Add a `Geo-LLM` tab to the dashboard that gives insight into the fine-tuning effort —
what the goal is, how QLoRA works, how training is progressing, the dataset, and how the
fine-tune stacks up against the RAG baseline. **Insight-only** this round: no chat, no model
serving, no conductor exposure. Tone is a **blend** — accessible/warm at the top, real science
below. The content **auto-updates** as the daily agent advances 0008, with no hand-editing.

Explicitly out of scope (decided in brainstorming): a "talk to it" chat panel (the adapter
isn't trained/served yet; revisit after 26e), and any change to the conductor or model serving.

## Where it lives

A new tab in `dashboard/template.html`, following the existing tab pattern (a
`<button data-tab="geollm">` in the tab bar + a `<div class="tab-content" id="tab-geollm">`).
No new page, no new runtime dependency.

## The five sections (top → bottom narrative spine)

1. **Hero blurb** — what Geo-LLM is and why. Copy (approved): "Teaching a small open model to
   write like Dr. George Calhoun — not by feeding it facts, but by steeping it in **millions of
   Geo Tokens** until the cadence, the contrarianism, and the turns of phrase are his. A
   companion to 'Ask Dad': where that quotes him, this aims to *sound* like him." Plus an
   "experiment in progress" pill.
2. **QLoRA explainer (the fun visual)** — flat diagram: `base model (frozen)` + `LoRA adapter
   (trainable)` → `Geo-LLM`, with a proportion bar conveying "~98% frozen / ~1–2% trained —
   cheap enough to run on the Mac mini." Plain-language, no jargon dump.
3. **The pipeline so far** — live 26a→26f tracker with per-step status (done / next / upcoming).
4. **The dataset at a glance** — real metric cards (voice examples, train/held-out split, source
   columns, corpus size, and **Geo Tokens** = computed token count of the training corpus) + one
   real sample training pair (prompt → his-voice answer).
5. **The scoreboard** — RAG baseline ("the bar to beat": grounding, citation coverage, refusal
   accuracy from `rag_eval.json`) vs the fine-tune column (populated from `voice_eval.json` when
   it exists; until then a clear "awaiting first voice-eval — unlocks at 26e" state).

## Data backbone (keeps it alive)

A new build-time generator computes a single JSON that the tab consumes:

- **`analysis/geo_llm_status.py`** → writes `data/analysis/geo_llm.json`. Pure/inspectable;
  deterministic helpers unit-testable offline (following `rag_eval`/`verdict_backfill` style).
- **`viz/build_dashboard.py`**: register a new placeholder `/*__GEO_LLM_DATA__*/` →
  `data/analysis/geo_llm.json`, with an empty-default so a missing file degrades gracefully
  (the build never breaks). Generation is invoked so a plain `make dashboard` refreshes it.
- **`dashboard/template.html`**: the tab markup + a small JS block that reads `GEO_LLM_DATA` and
  renders the five sections. No network calls.

### What `geo_llm.json` contains (all derived from real files; every field degrades)

| Field | Source |
|---|---|
| `dataset` (n_examples, n_train, n_heldout, n_columns, corpus_bytes, geo_tokens) | `data/training/{instruct,train,heldout}.jsonl`, `metadata.csv`, `corpus.txt` |
| `sample_pair` (prompt, answer) | first/curated record of `data/training/instruct.jsonl` |
| `pipeline` (26a–f: id, label, status) | **per-step artifact detection** (the plan file stays in `ready/` until all steps finish, so step status comes from concrete markers): 26a = dataset files exist; 26b = `rag_eval.json` exists; 26c = fine-tune notebook + `data/finetune_run/` split exist; 26d = `analysis/voice_eval.py` exists; 26e = adapter registered in the conductor (or an adapter dir exists); 26f = `voice_eval.json` has results |
| `qlora` (base_model, frozen_pct, trainable_pct) | 26c notebook / run config if discoverable, else sensible labeled defaults |
| `rag_baseline` (grounding, citation_coverage, abstention_accuracy) | `data/analysis/rag_eval.json` summary |
| `voice_eval` (or null) | `data/analysis/voice_eval.json` summary if present |

"Geo Tokens" is a playful name for the corpus token count; the hero's "millions" is flavor, and
the dataset card shows the real computed number so it's grounded. (If the true count reads below
a million, the card still shows the real figure — the hero line stays as approved copy.)

## Graceful degradation / states

- No `voice_eval.json` yet → scoreboard fine-tune column shows "awaiting first voice-eval".
- Any missing dataset file → that metric shows "—"; the section still renders.
- `geo_llm.json` entirely absent → placeholder empty-default renders an "in progress" tab, build
  still succeeds (mirrors how `EMBEDDINGS_DATA`/`PREDICTIONS_DATA` empty-defaults work today).

## Testing

- Unit-test the deterministic parts of `geo_llm_status.py` (dataset counting, pipeline-status
  derivation, token counting, summary extraction) on small fixtures — no network, no conductor.
- Build smoke: `make dashboard` emits `index.html` containing the new tab with both a populated
  and an empty `geo_llm.json` (graceful-degradation case).
- Reuse the responsive verification harness so the tab works on phones (roadmap #20 already
  shipped a responsive pass).

## Non-goals

- No chat / model serving / conductor changes.
- No new third-party dependencies.
- No edits to `roadmap.md`/`changelog.md` beyond noting the tab (human-curated).
