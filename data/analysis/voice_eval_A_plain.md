# Geo-LLM voice-fidelity eval

8/8 judged (blind A/B/C ranking by a T3 judge; plan 0008 step 26d).

| source | win-rate | avg rank | wins | appearances |
|--------|----------|----------|------|-------------|
| real | 100% | 1.00 | 8 | 8 |
| gemma-ft | 0% | 2.50 | 0 | 8 |
| gemma-plain | 0% | 2.50 | 0 | 8 |

## Head-to-head (fraction of shared trials the first source won)

- `gemma-ft_over_gemma-plain`: 50%
- `gemma-ft_over_real`: 0%
- `gemma-plain_over_gemma-ft`: 50%
- `gemma-plain_over_real`: 0%
- `real_over_gemma-ft`: 100%
- `real_over_gemma-plain`: 100%

## Deterministic style metrics (judge-independent)

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| gemma-ft | 150 | 0.353 | 18.4 | 101.6 | +49.0 |
| gemma-plain | 132 | 0.743 | 25.3 | 53.2 | +0.6 |
| real | 132 | 0.692 | 25.2 | 52.6 | — |

