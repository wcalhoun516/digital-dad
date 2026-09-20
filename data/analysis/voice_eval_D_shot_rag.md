# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 100% | 1.00 | 8 | 8 |
| gemma-ft-shot-rag | 0% | 2.50 | 0 | 8 |
| gemma-plain-shot-rag | 0% | 2.50 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `gemma-ft-shot-rag_over_gemma-plain-shot-rag`: 50%
- `gemma-ft-shot-rag_over_real`: 0%
- `gemma-plain-shot-rag_over_gemma-ft-shot-rag`: 50%
- `gemma-plain-shot-rag_over_real`: 0%
- `real_over_gemma-ft-shot-rag`: 100%
- `real_over_gemma-plain-shot-rag`: 100%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| gemma-ft-shot-rag | 150 | 0.364 | 20.6 | 79.0 | +26.4 |
| gemma-plain-shot-rag | 122 | 0.776 | 30.2 | 27.1 | -25.5 |
| real | 132 | 0.692 | 25.2 | 52.6 | — |

