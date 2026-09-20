# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 100% | 1.00 | 8 | 8 |
| gemma-plain-rag | 0% | 2.38 | 0 | 8 |
| gemma-ft-rag | 0% | 2.62 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `gemma-ft-rag_over_gemma-plain-rag`: 38%
- `gemma-ft-rag_over_real`: 0%
- `gemma-plain-rag_over_gemma-ft-rag`: 62%
- `gemma-plain-rag_over_real`: 0%
- `real_over_gemma-ft-rag`: 100%
- `real_over_gemma-plain-rag`: 100%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| gemma-ft-rag | 136 | 0.369 | 19.6 | 83.1 | +30.6 |
| gemma-plain-rag | 123 | 0.689 | 39.4 | 45.0 | -7.5 |
| real | 132 | 0.692 | 25.2 | 52.6 | — |

