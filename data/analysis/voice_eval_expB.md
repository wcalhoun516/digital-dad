# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 88% | 1.12 | 7 | 8 |
| gemma-plain-rag | 12% | 2.25 | 1 | 8 |
| gemma-ft-rag | 0% | 2.62 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `gemma-ft-rag_over_gemma-plain-rag`: 38%
- `gemma-ft-rag_over_real`: 0%
- `gemma-plain-rag_over_gemma-ft-rag`: 62%
- `gemma-plain-rag_over_real`: 12%
- `real_over_gemma-ft-rag`: 100%
- `real_over_gemma-plain-rag`: 88%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| gemma-ft-rag | 165 | 0.280 | 30.1 | 98.1 | +70.0 |
| gemma-plain-rag | 110 | 0.762 | 50.7 | 23.0 | -5.1 |
| real | 134 | 0.709 | 30.1 | 28.1 | — |

