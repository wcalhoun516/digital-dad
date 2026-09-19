"""Generate the voice eval's candidate answers — the step that was never automated.

``analysis.voice_trials`` builds a trial skeleton with ``real`` filled from the held-out
corpus and every model arm left as a paste-here placeholder. Somebody then had to hand-
produce two passages per trial, which is the actual reason the Geo-LLM eval sat unrun
between 2026-06 and 2026-09. This module fills them.

**Arms.** An arm is one thing being compared. ``real`` is not an arm — it comes from the
corpus. The rest are:

===============  =========  =========  ==================================================
arm              kind       retrieve   what it isolates
===============  =========  =========  ==================================================
``finetuned``    mlx        no         the QLoRA adapter's contribution
``base-3b``      mlx        no         the *same* base with no adapter — says what
                                       fine-tuning actually added, or cost
``rag``          conductor  yes        the shipped Ask Dad path (tier 2 + retrieval)
``prompted-12b`` conductor  no         tier 2 with a style prompt and no retrieval —
                                       says how much of RAG's score is retrieval at all
===============  =========  =========  ==================================================

The last two exist because ADR D17 compared a 3B model with no context against a 12B model
holding eight retrieved passages, and then drew a conclusion about fine-tuning. Two
variables moved at once. ``base-3b`` and ``prompted-12b`` are the controls that make the
next verdict mean something.

Following ``analysis.rag_eval`` and ``analysis.voice_eval``, everything networked or
GPU-bound sits behind one injected ``generate(arm, prompts) -> list[str]`` seam, so the
selection, assembly and completeness logic is unit-testable offline.
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .utils import DATA_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
FINETUNE_DIR = DATA_DIR / "finetune_run"
DEFAULT_TRIALS_OUT = REPO_ROOT / "eval" / "voice_trials_generated.json"
DEFAULT_ADAPTER_DIR = FINETUNE_DIR / "adapters_reshaped"

BASE_3B = "mlx-community/Qwen2.5-3B-Instruct-4bit"

# Capped near the reference excerpt length. D17's run used 400 with no repetition
# penalty, so the fine-tune wrote ~357 words against real's ~134 — which both depressed
# its type-token ratio and gave it room to loop. Length parity is part of a fair test.
DEFAULT_MAX_TOKENS = 220
DEFAULT_REPETITION_PENALTY = 1.1

_VAL_LOSS_RE = re.compile(r"Iter (\d+): Val loss ([0-9.]+)")
_PLACEHOLDER = "PASTE"


@dataclass(frozen=True)
class ArmSpec:
    """One comparison arm. ``kind`` picks which live generator the CLI wires."""

    name: str
    kind: str                      # "mlx" | "conductor"
    model: str | None = None       # mlx: HF id. conductor: unused (tier routes).
    adapter_dir: Path | None = None
    tier: int | None = None
    retrieve: bool = False


ARM_REGISTRY: dict[str, ArmSpec] = {
    "finetuned": ArmSpec(
        "finetuned", kind="mlx", model=BASE_3B,
        adapter_dir=FINETUNE_DIR / "adapters_reshaped_best",
    ),
    "base-3b": ArmSpec("base-3b", kind="mlx", model=BASE_3B, adapter_dir=None),
    "rag": ArmSpec("rag", kind="conductor", tier=2, retrieve=True),
    "prompted-12b": ArmSpec("prompted-12b", kind="conductor", tier=2, retrieve=False),
}


# --- checkpoint selection --------------------------------------------------------

def parse_val_losses(text: str) -> list[tuple[int, float]]:
    """Every ``Iter N: Val loss X`` pair in an mlx-lm training log, in file order.

    Tolerates the ``\\r``-heavy tqdm output mlx-lm writes.
    """
    return [(int(i), float(v)) for i, v in _VAL_LOSS_RE.findall(text.replace("\r", "\n"))]


def best_checkpoint(pairs: list[tuple[int, float]]) -> tuple[int, float]:
    """The ``(iter, loss)`` with the lowest validation loss; earliest iteration wins ties.

    The *final* adapter is the overfit one whenever training ran past the bottom — both
    Geo-LLM runs to date bottomed at iter 100 and then degraded — so evaluating
    ``adapters.safetensors`` measures the wrong model.
    """
    if not pairs:
        raise ValueError("no val-loss lines in the training log")
    return min(pairs, key=lambda p: (p[1], p[0]))


def checkpoint_filename(iteration: int) -> str:
    """mlx-lm's zero-padded per-checkpoint adapter filename."""
    return f"{iteration:07d}_adapters.safetensors"


# --- arm resolution --------------------------------------------------------------

def resolve_arms(names: list[str]) -> list[ArmSpec]:
    """Look up *names* in the registry, preserving order."""
    arms = []
    for name in names:
        if name == "real":
            raise ValueError("'real' is a corpus excerpt, not a generated arm")
        if name not in ARM_REGISTRY:
            raise ValueError(
                f"unknown arm {name!r}; known arms: {', '.join(sorted(ARM_REGISTRY))}"
            )
        arms.append(ARM_REGISTRY[name])
    return arms


# --- assembly --------------------------------------------------------------------

def fill_candidates(trials: list[dict], arm: str, texts: list[str]) -> list[dict]:
    """Write *texts* into each trial's ``candidates[arm]``, positionally.

    A length mismatch raises rather than zipping short: a silent truncation would pair
    every later answer with the wrong prompt, and the judge would never notice.
    """
    if len(texts) != len(trials):
        raise ValueError(
            f"{len(trials)} trials but {len(texts)} generations for arm {arm!r}"
        )
    for trial, text in zip(trials, texts):
        trial.setdefault("candidates", {})[arm] = (text or "").strip()
    return trials


def missing_candidates(trials: list[dict]) -> list[tuple[str, str]]:
    """``(trial_id, arm)`` for every candidate still empty or still a placeholder."""
    missing = []
    for trial in trials:
        for arm, text in trial.get("candidates", {}).items():
            if not text or not text.strip() or _PLACEHOLDER in text.upper():
                missing.append((trial.get("id", "?"), arm))
    return missing


def generate_all(
    trials: list[dict],
    arm_names: list[str],
    *,
    generate: Callable[[ArmSpec, list[str]], list[str]],
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Fill every arm in *arm_names* via the injected *generate*, then refuse to ship
    an incomplete trial set."""
    prompts = [t["prompt"] for t in trials]
    for arm in resolve_arms(arm_names):
        log(f"generating {arm.name} ({arm.kind}) for {len(prompts)} prompts")
        fill_candidates(trials, arm.name, generate(arm, prompts))
    gaps = missing_candidates(trials)
    if gaps:
        raise ValueError(f"incomplete trial set — empty candidates: {gaps}")
    return trials


def write_trials(trials: list[dict], path: Path) -> Path:
    """Write the ``{"description", "trials"}`` document ``voice_eval`` reads."""
    from .voice_trials import render_doc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(render_doc(trials), indent=2) + "\n")
    return path


# --- live seams (mlx + conductor) — not unit-tested; wired by the CLI -------------

def _stage_best_adapter(adapter_dir: Path, log_path: Path, dest: Path) -> tuple[Path, int, float]:
    """Copy the lowest-val-loss checkpoint into *dest* as mlx expects to find it."""
    import shutil

    iteration, loss = best_checkpoint(parse_val_losses(log_path.read_text(errors="replace")))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(adapter_dir / "adapter_config.json", dest / "adapter_config.json")
    ckpt = adapter_dir / checkpoint_filename(iteration)
    if not ckpt.exists():                      # the final iter is saved unprefixed
        ckpt = adapter_dir / "adapters.safetensors"
    shutil.copy(ckpt, dest / "adapters.safetensors")
    return dest, iteration, loss


def _live_mlx(arm: ArmSpec, *, max_tokens: int, repetition_penalty: float):
    from mlx_lm import generate as mlx_generate
    from mlx_lm import load

    from training.prepare import SYSTEM_PROMPT

    model, tokenizer = load(
        arm.model, adapter_path=str(arm.adapter_dir) if arm.adapter_dir else None
    )

    def run(_arm: ArmSpec, prompts: list[str]) -> list[str]:
        out = []
        for prompt in prompts:
            text = tokenizer.apply_chat_template(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": prompt}],
                add_generation_prompt=True, tokenize=False,
            )
            kwargs = {"max_tokens": max_tokens, "verbose": False}
            try:                                # mlx-lm moved sampler args across versions
                from mlx_lm.sample_utils import make_repetition_penalty
                kwargs["logits_processors"] = [make_repetition_penalty(repetition_penalty)]
            except Exception:                   # noqa: BLE001 - penalty is a nicety, not a gate
                pass
            out.append(mlx_generate(model, tokenizer, prompt=text, **kwargs))
        return out

    return run


def _live_conductor(arm: ArmSpec, *, max_tokens: int):
    from training.prepare import SYSTEM_PROMPT

    from .rag_eval import _live_generate, _live_retrieve

    generate = _live_generate(tier=arm.tier or 2)
    retrieve = _live_retrieve() if arm.retrieve else None

    def run(_arm: ArmSpec, prompts: list[str]) -> list[str]:
        out = []
        for prompt in prompts:
            sources = retrieve(prompt) if retrieve else []
            if retrieve:
                out.append(generate(prompt, sources))
            else:
                # No retrieval: the style prompt is the only thing shaping the voice.
                out.append(generate(f"{SYSTEM_PROMPT}\n\n{prompt}", []))
        return out

    _ = max_tokens
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.voice_candidates",
        description="Generate voice-eval candidate answers for one or more arms.",
    )
    parser.add_argument("--arms", default="finetuned,rag",
                        help="comma-separated; known: " + ",".join(sorted(ARM_REGISTRY)))
    parser.add_argument("--limit", type=int, default=8, help="number of trials")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=DEFAULT_TRIALS_OUT)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER_DIR)
    parser.add_argument("--train-log", type=Path, default=None,
                        help="mlx-lm log to pick the best checkpoint from "
                             "(default: newest logs/retrain_*.log)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--repetition-penalty", type=float,
                        default=DEFAULT_REPETITION_PENALTY)
    args = parser.parse_args(argv)

    arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]
    try:
        arms = resolve_arms(arm_names)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    from . import voice_trials as vt

    trials = vt.build_trials(vt.load_heldout(), limit=args.limit, seed=args.seed)
    if not trials:
        print("No held-out records — run `make finetune-prep` first.")
        return 2
    print(f"{len(trials)} trials; arms: {', '.join(arm_names)}")

    if any(a.kind == "mlx" and a.adapter_dir for a in arms):
        log_path = args.train_log
        if log_path is None:
            logs = sorted((REPO_ROOT / "logs").glob("retrain_*.log"))
            if not logs:
                print("No logs/retrain_*.log to pick a checkpoint from; pass --train-log.")
                return 2
            log_path = logs[-1]
        dest, it, loss = _stage_best_adapter(
            args.adapter_dir, log_path, FINETUNE_DIR / "adapters_reshaped_best"
        )
        print(f"best checkpoint: iter {it} (val loss {loss:.4f}) → {dest}")

    def dispatch(arm: ArmSpec, prompts: list[str]) -> list[str]:
        if arm.kind == "mlx":
            runner = _live_mlx(arm, max_tokens=args.max_tokens,
                               repetition_penalty=args.repetition_penalty)
        else:
            runner = _live_conductor(arm, max_tokens=args.max_tokens)
        return runner(arm, prompts)

    generate_all(trials, arm_names, generate=dispatch,
                 log=lambda m: print(f"  {m}", flush=True))
    out = write_trials(trials, args.output)
    print(f"\nTrial set → {out}\nNext: make voice-eval ARGS=\"--trials {out}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
