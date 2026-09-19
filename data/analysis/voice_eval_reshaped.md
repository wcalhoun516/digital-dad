# Geo-LLM voice — deterministic style metrics

8 trial(s); judge-independent companion to the blind A/B ranking (plan 0008 step 26d). `real` is the reference.

| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |
|--------|-------|-----|--------------|----------------|-----------------------|
| finetuned | 356 | 0.197 | 23.9 | 70.0 | +41.9 |
| rag | 139 | 0.675 | 27.4 | 48.4 | +20.2 |
| real | 134 | 0.709 | 30.1 | 28.1 | — |

