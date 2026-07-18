"""Embedding-model comparison harness (roadmap #27).

The corpus embedding model is **pinned** to ``sbert-mpnet-v2`` (decision D2):
cosine similarity is only meaningful within one vector space, so Semantic
Search, Ask Dad retrieval, and On This Day matching must all share it. Swapping
the model invalidates the whole index — so before we ever change it we need
numbers, not vibes. This module is that measurement mechanism.

Following ``analysis.rag_eval`` / ``analysis.voice_eval``, the compute-heavy,
networked part (actually embedding text through the conductor with a candidate
model) is isolated behind a single injected seam so all of the scoring and
comparison math is pure and unit-testable offline:

- ``embed(model_id, texts) -> list[vector]`` — embed a batch with one model.

Everything else — cosine ranking, retrieval-quality metrics (precision@k,
recall@k, MRR) against a small gold query set, and *baseline-agreement* metrics
(top-k overlap / rank correlation vs. the pinned model, which need no hand
labels) — are pure functions. The CLI (``python -m analysis.embedding_compare``
/ ``make embedding-compare``) wires the seam to the live conductor and is gated
on its reachability because a live pass loads/embeds with each candidate model.

The builder is deferred to future slices; this ships the offline harness.
"""

# Implemented in the TDD steps that follow this scaffold.
