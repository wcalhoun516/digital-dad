# training/ — Geo LLM dataset preparation

`python -m training` (or `make training`) turns the scraped corpus into the artifacts a
fine-tune needs. All outputs land in `data/training/` and are **gitignored** (never commit
them — regenerate from the corpus).

## Outputs

| File | Format | Contents |
|------|--------|----------|
| `finetune.jsonl` | `{"text": ...}` per line | raw body of every article (all 196) |
| `instruct.jsonl` | chat `messages` per line | quality-filtered instruction/chat pairs |
| `train.jsonl` | chat `messages` per line | fine-tune split (plan 0008) |
| `heldout.jsonl` | chat `messages` per line | held-out split for the voice eval |
| `corpus.txt` | plain text | concatenated bodies, chronological |
| `metadata.csv` | CSV | per-article slug/title/date/word_count/quality |

Each instruction record is `{"messages": [system, user, assistant]}`: the system prompt sets
his persona, the user asks "Write an analysis of <topic>" (topic derived from the title), and
the assistant message is the real article body.

## Quality filter

An article is excluded from the instruction outputs if `word_count < 400`, or (when
`data/analysis/linguistics.json` exists) if its type-token ratio is `< 0.3`.

## Train / held-out split (plan 0008, step 26a)

The split exists so the Geo LLM voice fine-tune (#26) can be measured against a clean
held-out set without contaminating the #25 RAG faithfulness eval:

- **Deterministic.** Each quality article is bucketed by a stable hash of its slug
  (`HELDOUT_FRACTION` of buckets → held-out). The partition is reproducible across runs and
  machines, independent of input order.
- **De-duplicated.** Records are keyed by slug, so duplicate manifest entries (the same
  article re-discovered via a different scraper tier) collapse to one record.
- **Leakage-free vs. the #25 eval.** Articles that an `eval/questions.json` question is
  grounded in (matched by normalized title) are reserved out of **both** splits, so the
  fine-tune never trains on the faithfulness eval's answers. When `eval/questions.json` is
  absent the exclusion is skipped with a warning (the fixture ships with plan 0007).

The shaping/splitting/overlap logic lives in `prepare.py` and is unit-tested in
`tests/test_prepare.py`.

## QLoRA fine-tune layer (plan 0008, step 26c)

`finetune_config.py` is the reproducible layer the fine-tune notebook
(`notebooks/finetune_qlora.ipynb`) imports, so the run is deterministic and
**leakage-safe**:

- **`QLoRAConfig`** — one frozen dataclass of hyperparameters (base model, LoRA
  rank/layers, iters, batch size, …) with sensible 16GB-M4 defaults. Swap bases by
  alias via `QLoRAConfig.for_base("qwen2.5-3b", train_iters=400)`; aliases are in
  `SMALL_BASES`.
- **`prepare_mlx_data()`** (`make finetune-prep`) — stages mlx-lm's expected
  `train.jsonl` / `valid.jsonl` in `data/finetune_run/` straight from 26a's
  `train.jsonl` / `heldout.jsonl`. **This replaces the notebook's old ad-hoc
  `random.shuffle` of `instruct.jsonl`**, which re-split *all* quality articles
  (including the ones 26a reserved out of the #25 RAG eval) and silently
  re-introduced eval leakage. Validation is now the leakage-free held-out set,
  verbatim.
- **`eval_prompts()`** — deterministic held-out prompts for the smoke generations.
- **`style_metrics()`** — the cheap style heuristics (TTR, sentence length, Calhoun
  "fingerprint" word rate), shared with the 26d voice eval.

These deterministic pieces are unit-tested in `tests/test_finetune_config.py`. The
actual MLX training run (model download + Metal compute) stays in the notebook —
it is not part of the offline test/verify path. `data/finetune_run/` (adapters,
fused weights, staged data) is gitignored.

## Fine-tune preflight (plan 0008, de-risks step 26c)

`finetune_preflight.py` (`make finetune-preflight`) is a pure, offline check run
**before** the expensive 26c training run, so the M4 isn't burned on a run that was
doomed at the data layer. It validates 26a's split against the `QLoRAConfig`:

- **chat-shape integrity** — every record is a non-empty system/user/assistant turn;
- **split disjointness** — no training body leaks into the held-out/valid set (keyed
  on assistant content, so a reworded prompt can't hide a leaked body);
- **sequence-length budget** — how many records' rendered prompts exceed the config's
  `max_seq_len` and would be dropped/truncated by mlx-lm (token count estimated at
  ~4 chars/token — no model download needed).

Report-only (exit 0) by default so it never reddens `make verify`; `--strict` exits 1
on any failing check (a future pre-run/CI gate). `--json` emits the machine-readable
report; `--max-seq-len` / `--base` override the config for what-if runs.

**Why this matters now:** on the real corpus the preflight passes shape + disjointness
but **fails the length budget — 100% of records exceed the default `max_seq_len=1024`**
(est. tokens median ~3,000, max ~5,300), because the assistant turn is a full article
body. The report turns this into an action: it suggests a `max_seq_len` — the smallest
power of two covering ~95% of records (currently **≈8192**, P95 ≈4,354 tokens) — so the
26c run either raises the window or chunks bodies instead of training on almost nothing.
The pure checks are unit-tested in `tests/test_finetune_preflight.py`.
