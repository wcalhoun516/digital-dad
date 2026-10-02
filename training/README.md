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
  verbatim. It is also **where the preflight is enforced** — see below.
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
on any failing check. `--json` emits the machine-readable report; `--max-seq-len` /
`--base` override the config for what-if runs.

### The gate (plan 0009, step 2)

Reporting was never enough. The preflight had been failing the length budget on the
real corpus since the day it was written, and it exits 0 by design, so nothing ever
stopped: **D15's fine-tune was trained on a dataset this tool was already rejecting**,
and its verdict was written up without anyone acting on the warning.

So the check now runs at the chokepoint instead of beside it. `prepare_mlx_data()` is
the only thing that writes the `train.jsonl` / `valid.jsonl` that `mlx_lm.lora --data`
reads — both `make finetune-prep` and the notebook go through it — and it **refuses to
stage a split that fails any check**, raising `PreflightError` and writing nothing.

- The refusal carries the **rendered report**, not just a failure flag, so the fix is
  in the error.
- If a previous run's files are still sitting in `data/finetune_run/`, the refusal
  **names them**: the trainer would read that directory and happily train on stale
  data while this run refused. They are named, not deleted.
- `force=True` (`make finetune-prep ARGS=--force`) overrides the gate — deliberately
  an argument and never a default, so reproducing D15's truncating run stays possible
  but cannot happen by accident. The returned `preflight_ok` records that it was used.
- The gate checks against the **config the run will actually use**, so raising
  `max_seq_len` in the notebook re-checks the budget at the new value.

On the real corpus the preflight now **passes** all three checks: plan 0009 step 1
made the records passage-level, taking the length budget from 100% over to 0%.

The pure checks are unit-tested in `tests/test_finetune_preflight.py`; the gate and its
override in `tests/test_finetune_config.py`.

## Registering the fine-tune for Ask Dad (plan 0008, step 26e)

Once a fine-tune is trained (26c) and you've added it to the **sibling conductor's**
`models.yaml`, you turn it on for the "Ask Dad" chat with a small **registration marker**
this repo reads at build time:

`data/analysis/geo_llm_registration.json` (gitignored — local/owner-produced):

```json
{
  "model_id": "geo-llm",          // required — the conductor model/function name to request
  "base_model": "gemma-2-2b",     // optional — shown for context
  "function": "geo-voice",        // optional — conductor function (defaults to "text")
  "tier": 2,                      // optional — pin a tier (defaults to the chat's tier toggle)
  "registered_at": "2026-06-20"   // optional — for your own bookkeeping
}
```

What it does:

- **`analysis/geo_llm_status.py`** reads the marker (`finetune_registration`) into the
  build-time `data/analysis/geo_llm.json`, surfacing a `finetune` block and flipping the
  26e pipeline step to **done**. No marker → `finetune: null`, step stays not-done.
- The dashboard's **"Ask Dad"** tab grows a **"Geo-LLM fine-tune"** toggle that is
  **hidden until a model is registered** and **off by default**. While off (or with no
  marker) Ask Dad is unchanged — the RAG `model: "auto"` conductor route. Flip it on and
  the chat request routes to your `model_id` (plus the marker's `function`/`tier` if set).

So the family's experience never changes until you both register the model **and** flip
the toggle — which is the "behind a flag, default off" intent of 26e. Deleting the marker
fully reverts it. The marker reader is unit-tested in `tests/test_geo_llm_status.py`; the
toggle plumbing in `tests/test_dashboard_geo_flag.py`.

> Still owner-interactive (not done by the daily agent): the actual `models.yaml` edit in
> `local-llm-conductor`, and the live judged comparison (26f) that decides fine-tune vs RAG.

## DAPT — continued pretraining on his raw prose (roadmap #54)

ADR D19 found the instruction-pair LoRA *worse* than its own un-tuned base: on ~453K tokens,
"Write an analysis of X" → article is cheapest to fit by copying surface markers. DAPT keeps
the same tokens and drops the format — `{"text": ...}` records, no system prompt, no user
turn. `training/dapt.py` builds that set; `make dapt-prep` stages it.

```bash
make training     # writes the instruction split + metadata.csv the DAPT set is derived from
make dapt-prep    # → data/finetune_run/dapt/{train,valid}.jsonl, or exit 1 if the preflight fails
```

**Same tokens, different objective**, so the comparison holds the articles fixed. Membership is
read from `make training`'s own `metadata.csv` (inheriting its quality filter rather than
copying it), and the split is recomputed with `prepare.split_articles` +
`prepare.eval_grounded_slugs`: DAPT train is exactly the instruction train articles, DAPT valid
exactly the held-out ones, and the eval-grounded articles stay out of both.

It has its own `--data` directory because `mlx_lm.lora` reads every file in it — text records
must never sit beside chat records. Staging refuses, writing nothing, unless all five checks
pass (`ARGS=--force` overrides):

| Check | Fails when |
|-------|-----------|
| text shape | a record is empty, or is a chat record rather than plain `{"text"}` |
| split disjoint | an identical record is on both sides |
| length budget | a record's estimated tokens exceed `max_seq_len` |
| same split | an instruction passage is missing from its side (a stale `make training`) or found on the other |
| heldout 8-grams | DAPT train holds a held-out 8-gram the instruction train does **not** already hold |

The last check is relative on purpose. He reused passages across columns, so the instruction
train already shares **318** 8-grams with its own held-out set — an absolute-zero bar would
fail both arms equally. What must hold is that DAPT adds none, so its validation loss is not
flattered relative to the arm it is compared with.

On the corpus as of 2026-10-02: **483** train records from 140 articles, **112** valid from 35,
est. tokens median 913 / max 972 against a 1024 window — fewer records than the instruction
split's 540, because no window is spent on prompts.

An mlx-lm config that changes only the objective relative to D19's run (same base, same
adapter shape, same learning rate) — save it as e.g. `data/finetune_run/gemma4_dapt.yaml`
(that directory is gitignored):

```yaml
model: "mlx-community/gemma-4-e4b-it-4bit"
train: true
data: "data/finetune_run/dapt"
adapter_path: "data/finetune_run/adapters_gemma4_e4b_dapt"
fine_tune_type: lora
iters: 1000          # 483 records at batch 1 ≈ 2 epochs; D19's runs bottomed before 1
steps_per_eval: 50
val_batches: 12
save_every: 50
batch_size: 1
max_seq_length: 1024
grad_checkpoint: true
mask_prompt: false   # there is no prompt — every token is his
learning_rate: 1.0e-4
seed: 42
num_layers: 16
lora_parameters:
  rank: 16
  scale: 32.0
  dropout: 0.05
```

> Not done here: the training run (owner GPU hours) and the measurement. A DAPT adapter on an
> instruction-tuned base can erode instruction-following, so the voice eval needs a
> `gemma-dapt` arm in `make voice-candidates` before any verdict — the next slice of #54.
