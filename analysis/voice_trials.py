"""Voice-trials builder for the Geo-LLM voice eval (plan 0008 step 26d prep).

The 26d harness (``analysis.voice_eval``) consumes a ``voice_trials.json`` of held-out
prompts plus candidate passages to blind-rank. Today the only input is
``eval/voice_trials.example.json`` — a hand-authored template with placeholder text. This
module produces the **real** skeleton deterministically from 26a's held-out split
(``data/training/heldout.jsonl``): each trial carries the held-out ``prompt`` (the user
turn) and a length-balanced ``real`` excerpt (a genuine Calhoun passage), with the ``rag``
and ``finetuned`` candidates left as paste-here placeholders for the owner/conductor.

Because the prompts come straight from the held-out split — which 26a already builds to
exclude the #25 RAG-eval-grounded articles — the trials are leakage-free by construction.

Pure and offline (stdlib only; no conductor, no paid T3 calls). The generated file embeds
real article bodies, so it is gitignored like ``heldout.jsonl`` and must not be committed.
"""

import argparse
import json
import random
from pathlib import Path

from .utils import DATA_DIR

ROOT_DIR = Path(__file__).resolve().parent.parent
HELDOUT_PATH = DATA_DIR / "training" / "heldout.jsonl"
# Same path analysis.voice_eval reads its trials from, so `make voice-eval` picks it up.
TRIALS_OUT_PATH = ROOT_DIR / "eval" / "voice_trials.json"

# The real model answers are filled in by the owner once the 26c adapter exists and the
# conductor is up; mirror the example template's wording.
RAG_PLACEHOLDER = "<paste the Ask Dad RAG answer to this prompt here>"
FINETUNED_PLACEHOLDER = "<paste the 26c fine-tuned model's answer here>"

# A few paragraphs — long enough to judge voice, short enough that `real` doesn't out
# itself to the judge by sheer length next to the model answers.
DEFAULT_EXCERPT_CHARS = 900

_DESCRIPTION = (
    "Geo-LLM voice-fidelity trials (plan 0008 step 26d), built deterministically from the "
    "26a held-out split. Each trial is one held-out prompt plus the candidate passages to "
    "blind-rank for how well they read like Dr. George Calhoun. 'real' is a genuine excerpt "
    "(the gold reference); 'rag' (Ask Dad) and 'finetuned' (the 26c QLoRA model) are "
    "placeholders for the owner to paste once those exist. Prompts come from the held-out "
    "split, which excludes the #25 RAG-eval articles, so they don't overlap the faithfulness "
    "eval. This file embeds real article bodies and is gitignored — do not commit it."
)


def _turn(record: dict, role: str) -> str:
    """Return the first message content for *role*, or '' if absent."""
    for msg in record.get("messages", []):
        if msg.get("role") == role:
            return msg.get("content", "")
    return ""


def derive_prompt(record: dict) -> str:
    """The held-out user turn that elicits his voice (the trial prompt)."""
    return _turn(record, "user")


def excerpt(text: str, max_chars: int = DEFAULT_EXCERPT_CHARS) -> str:
    """Trim *text* to at most *max_chars*, preferring a clean sentence boundary.

    Short text is returned stripped and unchanged. Otherwise, if a sentence terminator
    (``.!?``) falls in the back half of the window, the passage is cut there and returned
    as a complete sentence — no ellipsis. This matters for the blind voice ranking: a
    fragment that ends mid-thought (``…``) could tip the judge off that it's an excerpt
    and bias the comparison. Failing a usable sentence break, it falls back to the last
    whole word so the passage never ends mid-word.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    sentence_end = max(window.rfind(c) for c in ".!?")
    if sentence_end >= max_chars // 2:
        return window[: sentence_end + 1].rstrip()
    cut = window.rsplit(" ", 1)[0].rstrip()
    return f"{cut}…"


def build_trial(
    record: dict,
    idx: int,
    *,
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    rag: str = RAG_PLACEHOLDER,
    finetuned: str = FINETUNED_PLACEHOLDER,
) -> dict:
    """Shape one held-out record into a voice-eval trial with a ``vNN`` id."""
    return {
        "id": f"v{idx:02d}",
        "prompt": derive_prompt(record),
        "candidates": {
            "real": excerpt(_turn(record, "assistant"), excerpt_chars),
            "rag": rag,
            "finetuned": finetuned,
        },
    }


def build_trials(
    records: list[dict],
    *,
    limit: int | None = None,
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    seed: int | None = None,
) -> list[dict]:
    """Build trials from held-out *records*.

    Records missing a user prompt or an assistant body are skipped. With *seed* the
    selection is a reproducible shuffle (so the owner can sample representatively);
    without it, file order is preserved. *limit* caps the number of trials; ids are
    sequential over the trials actually emitted.
    """
    ordered = list(records)
    if seed is not None:
        random.Random(seed).shuffle(ordered)

    trials: list[dict] = []
    for record in ordered:
        if limit is not None and len(trials) >= limit:
            break
        if not derive_prompt(record) or not _turn(record, "assistant"):
            continue
        trials.append(build_trial(record, len(trials) + 1, excerpt_chars=excerpt_chars))
    return trials


def render_doc(trials: list[dict]) -> dict:
    """Wrap *trials* with the self-describing header voice_eval ignores but humans read."""
    return {"description": _DESCRIPTION, "trials": trials}


def load_heldout(path: Path = HELDOUT_PATH) -> list[dict]:
    """Read a JSONL of instruct records; return [] if the file is absent."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def write_trials(doc: dict, path: Path = TRIALS_OUT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def run():
    parser = argparse.ArgumentParser(
        description="Build a voice_trials.json skeleton from the 26a held-out split."
    )
    parser.add_argument("--heldout", type=Path, default=HELDOUT_PATH)
    parser.add_argument("--out", type=Path, default=TRIALS_OUT_PATH)
    parser.add_argument("--limit", type=int, default=None, help="cap the number of trials")
    parser.add_argument("--excerpt-chars", type=int, default=DEFAULT_EXCERPT_CHARS)
    parser.add_argument(
        "--seed", type=int, default=None, help="reproducible shuffle before --limit"
    )
    args = parser.parse_args()

    records = load_heldout(args.heldout)
    if not records:
        print(
            f"No held-out records at {args.heldout}.\n"
            "Run `make training` first to build data/training/heldout.jsonl (plan 0008 26a)."
        )
        return

    trials = build_trials(
        records, limit=args.limit, excerpt_chars=args.excerpt_chars, seed=args.seed
    )
    write_trials(render_doc(trials), args.out)

    # Redacted summary only — never dump the licensed excerpt text.
    real_lens = [len(t["candidates"]["real"]) for t in trials]
    span = f"{min(real_lens)}–{max(real_lens)}" if real_lens else "0"
    print(f"Wrote {len(trials)} trial(s) -> {args.out}")
    print(
        f"  prompts + `real` excerpts filled (real length {span} chars); "
        "`rag`/`finetuned` left as placeholders for the owner to paste."
    )


if __name__ == "__main__":
    run()
