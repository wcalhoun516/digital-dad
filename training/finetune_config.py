"""Reproducible QLoRA config + leakage-safe data staging (plan 0008, step 26c).

`notebooks/finetune_qlora.ipynb` imports from here so the fine-tune run is
**reproducible** and trains on **26a's leakage-free split** (`train.jsonl` /
`heldout.jsonl`) rather than an ad-hoc re-shuffle of `instruct.jsonl` (which
includes the articles reserved out of the #25 RAG eval and would re-introduce
the leakage 26a was built to prevent).

The deterministic pieces here — config resolution, mlx-lm data staging, eval-prompt
selection, style metrics — are unit-tested in `tests/test_finetune_config.py`. The
actual MLX training run (model download + Metal compute) lives in the notebook and
is not part of this module.

Run `python -m training.finetune_config` (or `make finetune-prep`) to stage the
mlx-lm `train.jsonl` / `valid.jsonl` from the 26a split — offline and free.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TRAINING_DIR = ROOT_DIR / "data" / "training"
FINETUNE_DIR = ROOT_DIR / "data" / "finetune_run"

# Small bases that fit a 16GB M4 with 4-bit quantization + LoRA. Keys are short
# aliases; values are the HuggingFace ids the notebook / mlx-lm load.
SMALL_BASES = {
    "phi3-mini": "microsoft/Phi-3-mini-4k-instruct",
    "phi3.5-mini": "microsoft/Phi-3.5-mini-instruct",
    "gemma-2-2b": "google/gemma-2-2b-it",
    "smollm2-1.7b": "HuggingFaceTB/SmolLM2-1.7B-Instruct",
    "llama-3.2-3b": "meta-llama/Llama-3.2-3B-Instruct",
    "qwen2.5-3b": "Qwen/Qwen2.5-3B-Instruct",
}

# Matches phi3:mini in the Ollama roster, so the fine-tune is comparable to the
# stock conductor baseline the notebook contrasts against.
DEFAULT_BASE = SMALL_BASES["phi3-mini"]


@dataclass(frozen=True)
class QLoRAConfig:
    """Hyperparameters for one mlx-lm LoRA run. Defaults are the smallest viable
    settings for a 16GB M4 (4-bit base + small LoRA adapter)."""

    base_model: str = DEFAULT_BASE
    lora_layers: int = 8
    lora_rank: int = 8
    train_iters: int = 200
    batch_size: int = 2
    learning_rate: float = 1e-4
    max_seq_len: int = 1024
    conductor_url: str = "http://127.0.0.1:8080/v1"

    @classmethod
    def for_base(cls, name: str, **overrides) -> "QLoRAConfig":
        """Build a config for a base given by registry alias OR full HF id, with
        optional hyperparameter overrides."""
        base = SMALL_BASES.get(name, name)
        return cls(base_model=base, **overrides)

    def to_dict(self) -> dict:
        return asdict(self)


def load_jsonl(path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank lines."""
    records: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path, records) -> None:
    """Write dicts to a JSONL file (one JSON object per line)."""
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def user_prompt(record: dict) -> str | None:
    """The user-turn content of a chat record, or None if absent."""
    for m in record.get("messages", []):
        if m.get("role") == "user":
            return m.get("content")
    return None


def prepare_mlx_data(training_dir=TRAINING_DIR, finetune_dir=FINETUNE_DIR) -> dict:
    """Stage mlx-lm's expected ``train.jsonl`` / ``valid.jsonl`` from 26a's split.

    ``mlx_lm.lora`` reads ``train.jsonl`` and ``valid.jsonl`` from its ``--data``
    directory. We copy 26a's leakage-free ``train.jsonl`` → mlx ``train.jsonl`` and
    ``heldout.jsonl`` → mlx ``valid.jsonl`` **verbatim**, so training uses exactly
    the deterministic, eval-safe split — no random re-shuffle, no eval-grounded
    contamination. Returns ``{"n_train", "n_valid"}``.
    """
    training_dir = Path(training_dir)
    finetune_dir = Path(finetune_dir)
    train_src = training_dir / "train.jsonl"
    heldout_src = training_dir / "heldout.jsonl"
    missing = [str(p) for p in (train_src, heldout_src) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing 26a split file(s): " + ", ".join(missing) + ". Run `make training` first."
        )
    train_records = load_jsonl(train_src)
    valid_records = load_jsonl(heldout_src)
    finetune_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(finetune_dir / "train.jsonl", train_records)
    write_jsonl(finetune_dir / "valid.jsonl", valid_records)
    return {"n_train": len(train_records), "n_valid": len(valid_records)}


def eval_prompts(records, n: int = 5) -> list[str]:
    """Deterministic held-out prompts for smoke generations.

    Takes the first ``n`` distinct user prompts in the records' given order (the
    records come from the deterministically-ordered ``heldout.jsonl``), so the
    eval set is stable across runs.
    """
    prompts: list[str] = []
    seen: set[str] = set()
    for r in records:
        p = user_prompt(r)
        if p and p not in seen:
            seen.add(p)
            prompts.append(p)
        if len(prompts) >= n:
            break
    return prompts


def style_metrics(text: str, distinctive_words: set) -> dict:
    """Cheap deterministic style metrics for a generated passage.

    Reused by the notebook (26c) and the voice-fidelity eval (26d) so both score
    style the same way.
    """
    words = re.findall(r"\b[a-z]+\b", text.lower())
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    sentences = [s for s in sentences if len(s.split()) > 3]

    word_count = len(words)
    vocab_size = len(set(words))
    ttr = vocab_size / word_count if word_count else 0
    avg_sentence_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    fingerprint_hits = sum(1 for w in words if w in distinctive_words)
    fingerprint_rate = fingerprint_hits / word_count * 1000 if word_count else 0

    return {
        "word_count": word_count,
        "type_token_ratio": round(ttr, 3),
        "avg_sentence_len": round(avg_sentence_len, 1),
        "fingerprint_hits_per_1k": round(fingerprint_rate, 1),
    }


def run():
    """CLI: stage the mlx-lm data from 26a's split (offline, free)."""
    try:
        counts = prepare_mlx_data()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return
    print(
        f"Staged mlx-lm data in {FINETUNE_DIR} from 26a's leakage-free split: "
        f"train={counts['n_train']}, valid/heldout={counts['n_valid']}."
    )


if __name__ == "__main__":
    run()
