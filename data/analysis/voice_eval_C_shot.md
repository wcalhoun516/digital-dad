# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 100% | 1.00 | 8 | 8 |
| gemma-plain-shot | 0% | 2.12 | 0 | 8 |
| gemma-ft-shot | 0% | 2.88 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `gemma-ft-shot_over_gemma-plain-shot`: 12%
- `gemma-ft-shot_over_real`: 0%
- `gemma-plain-shot_over_gemma-ft-shot`: 88%
- `gemma-plain-shot_over_real`: 0%
- `real_over_gemma-ft-shot`: 100%
- `real_over_gemma-plain-shot`: 100%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| gemma-ft-shot | 162 | 0.314 | 20.4 | 76.5 | +24.0 |
| gemma-plain-shot | 140 | 0.727 | 33.1 | 50.6 | -1.9 |
| real | 132 | 0.692 | 25.2 | 52.6 | — |

