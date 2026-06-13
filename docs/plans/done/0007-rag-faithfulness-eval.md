# Plan 0007 — RAG faithfulness eval harness

## Goal

Establish a measurable baseline for whether "Ask Dad" is trustworthy: does it answer using
real passages from the corpus, cite them correctly, and avoid hallucinating? This is the
groundwork the whole "evidenced, not hallucinated" goal (see `docs/goals.md`) rests on, and
the baseline any future fine-tune (#26) must beat.

## Context

- Retrieval + generation today: embed query (sbert via conductor) → top-8 articles by cosine
  → conductor chat completion grounded in their snippets → answer with citations. The same
  retrieval logic exists in `analysis/semantic_search.py` (`search()`) and is mirrored in the
  dashboard's Ask Dad JS.
- LLM access via the conductor (T2/T3). An eval can use a stronger model as judge (T3).
- This is analysis/eval tooling, not a UI change — a new module (e.g. `analysis/rag_eval.py`
  or an `eval/` package) is appropriate.

## Steps (use `superpowers:test-driven-development` for the scorers)

1. **Held-out question set:** generate or hand-write a set of questions answerable from the
   corpus (and a few deliberately *not* answerable, to test refusal/abstention). Store as a
   small fixture (`eval/questions.json` or similar).
2. **Run retrieval+generation** for each question (reuse `semantic_search.search()` so the
   eval matches production retrieval).
3. **Score faithfulness:**
   - *Citation accuracy:* are the cited articles actually in the retrieved set / do the cited
     passages support the claims? (LLM-judge with the source passages provided.)
   - *Hallucination rate:* fraction of claims not grounded in any retrieved passage.
   - *Abstention:* does it decline on unanswerable questions instead of inventing?
4. **Report:** write `data/analysis/rag_eval.json` + a readable summary; print headline
   numbers. Make it re-runnable so future changes can be compared against this baseline.

## Verification

- Run the harness end-to-end on the small question set; sanity-check that the scores are
  plausible (spot-check a couple of judgments by hand).
- TDD the deterministic scoring helpers (grounding/citation matching) on fixtures.
- `superpowers:verification-before-completion`: paste the headline metrics into the PR.

## Out of scope

- The actual QLoRA fine-tune and voice-fidelity comparison (#26) — this only builds the eval
  the fine-tune will be measured against. Embedding-model comparison is #27.
