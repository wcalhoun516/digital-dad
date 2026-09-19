# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 75% | 1.25 | 6 | 8 |
| rag | 25% | 1.75 | 2 | 8 |
| finetuned | 0% | 3.00 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `finetuned_over_rag`: 0%
- `finetuned_over_real`: 0%
- `rag_over_finetuned`: 100%
- `rag_over_real`: 25%
- `real_over_finetuned`: 100%
- `real_over_rag`: 75%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| finetuned | 356 | 0.197 | 23.9 | 70.0 | +41.9 |
| rag | 139 | 0.675 | 27.4 | 48.4 | +20.2 |
| real | 134 | 0.709 | 30.1 | 28.1 | — |

