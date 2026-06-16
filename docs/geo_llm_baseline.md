# Geo LLM — pre-fine-tune baseline (26b)

Pre-fine-tune baseline for the Geo LLM (#26). These are the numbers any fine-tuned George-Calhoun-voice model must beat on faithfulness; the voice half is filled in by the 26d voice-fidelity harness.

- **Captured:** 2026-06-14
- **Source:** analysis.rag_eval (#25, plan 0007), run 2026-06-13 (14 held-out questions)

## Factuality (RAG / Ask Dad) — the bar to beat

| Metric | Baseline | Better |
| --- | --- | --- |
| `n_questions` | 14 | — |
| `n_answerable` | 10 | — |
| `n_unanswerable` | 4 | — |
| `total_claims` | 75 | — |
| `grounded_claims` | 64 | — |
| `grounding_rate` | 85.3% | higher ↑ |
| `hallucination_rate` | 14.7% | lower ↓ |
| `abstention_accuracy` | 100.0% | higher ↑ |
| `false_abstention_rate` | 10.0% | lower ↓ |
| `citation_coverage` | 60.0% | — |

A fine-tune must **beat** (not merely match) these on the four targeted faithfulness metrics to justify replacing RAG. `citation_coverage` is RAG-specific and informational only.

## Voice fidelity

_pending_ — Populated by the 26d voice-fidelity eval harness (blind A/B vs RAG and real excerpts).

