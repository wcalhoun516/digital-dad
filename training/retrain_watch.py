"""Retrain the LoRA adapter when the corpus has actually grown.

**Why this exists.** D15, D19 and D20 measured LoRA three times at ~453k tokens and it
never beat the plain model. But every one of those runs was **token-starved** — validation
loss bottoms at **0.74 epochs**, before the model has read the corpus once. The open
question is therefore *corpus size*, not hyperparameters, and the useful thing to automate
is "re-measure when there is meaningfully more text", not "search harder on the same text".

So this module does two jobs:

1. **Decide.** Has the corpus changed (D3 fingerprint) *and* grown enough to be worth
   hours of GPU? Three newly scraped articles must not trigger a run; a book should.
2. **Execute.** prepare → preflight → train → (optionally) evaluate, stopping at the first
   failure, and appending a row to the eval history with **corpus size beside the score**
   so the "how much text is enough" curve accumulates on its own (roadmap #60).

Every decision is a pure function; the subprocess work sits behind one injected ``step``
seam, so the logic is unit-tested offline and no test starts a real training run.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "training" / "retrain_state.json"
CONFIG_PATH = ROOT / "data" / "finetune_run" / "gemma4_lora_long.yaml"

# ~5.5% of the current corpus. Small enough that one ingested book (~106k tokens) or a
# batch of correspondence clears it; large enough that a normal weekly scrape (a handful
# of columns, ~3k tokens) does not spend three hours of GPU to re-learn nothing.
DEFAULT_MIN_NEW_TOKENS = 25_000
WORDS_TO_TOKENS = 4 / 3


@dataclass(frozen=True)
class Decision:
    due: bool
    reason: str
    new_tokens: int = 0


@dataclass(frozen=True)
class PipelineResult:
    ok: bool
    failed_at: str | None = None
    ran: tuple[str, ...] = ()


# --- measurement -----------------------------------------------------------------

def corpus_state(articles: list[dict]) -> dict:
    """Fingerprint + size of the corpus. The fingerprint matches D3's convention."""
    parts, words = [], 0
    for a in sorted(articles, key=lambda x: x.get("slug", "")):
        body = a.get("body") or ""
        h = a.get("content_hash") or hashlib.md5(body.encode()).hexdigest()
        parts.append(f"{a.get('slug', '')}:{h}")
        words += len(body.split())
    return {
        "fingerprint": hashlib.md5("|".join(parts).encode()).hexdigest(),
        "articles": len(articles),
        "words": words,
        "approx_tokens": int(words * WORDS_TO_TOKENS),
    }


# --- decision --------------------------------------------------------------------

def retrain_decision(
    current: dict, last: dict | None, *, min_new_tokens: int = DEFAULT_MIN_NEW_TOKENS
) -> Decision:
    """Is a fresh LoRA run warranted?

    The fingerprint is the authority on *whether* the corpus changed — token counts are
    estimates and wobble. Size only decides whether the change is big enough to pay for.
    """
    if not last:
        return Decision(True, "no prior training run recorded")

    if current.get("fingerprint") == last.get("fingerprint"):
        return Decision(False, "corpus unchanged since the last run (same fingerprint)")

    delta = int(current.get("approx_tokens", 0)) - int(last.get("approx_tokens", 0))
    if abs(delta) < min_new_tokens:
        return Decision(
            False,
            f"corpus changed but only by {delta:+,} tokens "
            f"(threshold {min_new_tokens:,}) — not worth a run",
            delta,
        )
    direction = "grew" if delta > 0 else "shrank"
    return Decision(
        True,
        f"corpus {direction} by {abs(delta):,} tokens to {current.get('approx_tokens', 0):,} "
        f"({current.get('articles', 0)} documents) — retrain due",
        delta,
    )


# --- state -----------------------------------------------------------------------

def load_last_state(path: Path = STATE_PATH) -> dict | None:
    """The last recorded training state, or None. A corrupt file is not fatal — it
    would otherwise wedge every future run."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def record_state(state: dict, path: Path = STATE_PATH) -> Path:
    """Persist the corpus state a training run was performed against."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**state, "recorded_at": date.today().isoformat()}, indent=2))
    return path


# --- pipeline --------------------------------------------------------------------

def _default_step(name: str, cmd: list[str]) -> int:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def run_pipeline(
    *,
    step: Callable[[str, list[str]], int] = _default_step,
    train: bool = True,
    evaluate: bool = False,
    config: Path = CONFIG_PATH,
) -> PipelineResult:
    """prepare → preflight → train → evaluate, stopping at the first non-zero exit.

    ``preflight`` runs ``--strict`` on purpose: it is the gate that caught a real
    train/heldout leak, and a run that forces past it produces numbers that cannot be
    compared to anything. ``evaluate`` is opt-in because the judge costs real money.
    """
    py = str(ROOT / ".venv" / "bin" / "python")
    steps: list[tuple[str, list[str]]] = [
        ("prepare", [py, "-m", "training"]),
        ("preflight", [py, "-m", "training.finetune_preflight", "--strict"]),
    ]
    if train:
        steps.append(("train", [str(ROOT / ".venv" / "bin" / "mlx_lm.lora"),
                                "--config", str(config)]))
    if evaluate:
        steps.append(("evaluate", [py, "-m", "analysis.voice_candidates",
                                   "--arms", "gemma-plain,gemma-ft"]))

    ran: list[str] = []
    for name, cmd in steps:
        ran.append(name)
        if step(name, cmd) != 0:
            return PipelineResult(False, name, tuple(ran))
    return PipelineResult(True, None, tuple(ran))


# --- CLI -------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m training.retrain_watch",
        description="Retrain the LoRA adapter when the corpus has meaningfully grown.",
    )
    parser.add_argument("--run", action="store_true",
                        help="execute the pipeline when a retrain is due (default: report only)")
    parser.add_argument("--force", action="store_true",
                        help="run even if the corpus has not grown enough")
    parser.add_argument("--evaluate", action="store_true",
                        help="also generate candidates and judge (costs paid T3 calls)")
    parser.add_argument("--min-new-tokens", type=int, default=DEFAULT_MIN_NEW_TOKENS)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    args = parser.parse_args(argv)

    from analysis.utils import load_articles

    current = corpus_state(load_articles())
    last = load_last_state(args.state)
    decision = retrain_decision(current, last, min_new_tokens=args.min_new_tokens)

    print("LoRA retrain watch")
    print(f"  corpus now : {current['articles']} documents, {current['words']:,} words "
          f"(~{current['approx_tokens']:,} tokens)")
    if last:
        print(f"  last run   : {last.get('articles')} documents, "
              f"~{last.get('approx_tokens', 0):,} tokens "
              f"({last.get('recorded_at', 'unknown date')})")
    else:
        print("  last run   : none recorded")
    print(f"  decision   : {'RETRAIN DUE' if decision.due else 'not due'} — {decision.reason}")

    if not args.run:
        # Report-only, mirroring manifest_check: exit 1 signals "due" to a caller.
        return 1 if decision.due else 0

    if not decision.due and not args.force:
        print("\nNothing to do. Use --force to run anyway.")
        return 0

    result = run_pipeline(train=True, evaluate=args.evaluate)
    if not result.ok:
        print(f"\nPipeline FAILED at '{result.failed_at}'. State not updated.")
        return 2

    record_state(current, args.state)
    print(f"\nPipeline complete ({' → '.join(result.ran)}). State recorded at {args.state}.")
    print("Corpus size is stored beside the run so the 'how much text is enough' curve "
          "accumulates (roadmap #60).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
