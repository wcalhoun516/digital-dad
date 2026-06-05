"""Track Record — evidence-augmented verdict backfill (plan 0004 step 1).

The verdict pass in ``predictions.py`` asks an LLM to rule on each prediction purely from
its own memory. This module adds an *evidence-grounded* pass: for each prediction it
gathers external evidence (e.g. a web search) and asks a model to return a verdict **with
the sources it relied on**, so the family can see the receipts behind each ruling.

Results land in ``evidence_*`` fields that take precedence over the ungrounded
``llm_verdict`` but never over a human ruling (see
``analysis/adjudicate.effective_verdict``). The grounded pass is therefore still advisory:
a family member's adjudication always wins.

The compute-heavy, networked, paid parts are isolated behind two injected seams so the
logic here is fully unit-testable offline:

- ``gather_evidence(prediction) -> list[source]`` — returns evidence dicts
  (``{title, url, snippet}``). The owner wires this to a real search when the conductor
  (with web search) is up; tests pass a fake.
- ``chat(prompt) -> str`` — a single text completion. The CLI wires this to the conductor
  at tier 3; tests pass a fake.

Like the extraction pass, ``run_backfill`` is resumable (skips predictions that already
have an ``evidence_verdict``) and incremental (invokes a ``save`` callback every N).

The CLI (``python -m analysis.verdict_backfill`` / ``make backfill-verdicts``) is an
owner-gated operation: it refuses to run if the conductor is unreachable, because a live
pass makes paid T3 calls. Run it deliberately, not from automation.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .utils import DATA_DIR

VALID_VERDICTS = ("vindicated", "wrong", "mixed", "unfalsifiable", "pending")
VALID_CONFIDENCE = ("low", "medium", "high")

DEFAULT_PATH = DATA_DIR / "analysis" / "predictions.json"

BACKFILL_PROMPT = """You are auditing a single prediction made by Dr. George Calhoun in a Forbes article. Determine whether it turned out RIGHT, WRONG, or remains unresolved — grounding your ruling in the evidence provided below.

RULES:
- The prediction was made on {prediction_date}. Judge only by what happened AFTER that date.
- Rely on the EVIDENCE below. If it is insufficient, you may use well-known facts, but say so.
- "vindicated" = the core claim came true. "wrong" = events clearly contradicted it.
- "mixed" = partially right (right direction, wrong magnitude; right short-term, wrong long-term).
- "pending" = it concerns a date after {current_date}, or the outcome genuinely cannot be determined.
- "unfalsifiable" = too vague to ever judge.

Return ONLY a JSON object (no markdown, no commentary):
{{
  "verdict": one of "vindicated" | "wrong" | "mixed" | "unfalsifiable" | "pending",
  "reasoning": "2-4 sentences citing what actually happened, referencing the evidence",
  "confidence": "low" | "medium" | "high",
  "sources": ["url or short citation", ...]
}}

Current date: {current_date}

PREDICTION
- topic: {topic}
- claim: {claim}

EVIDENCE
{evidence}"""


def format_evidence(sources: list[dict]) -> str:
    """Render gathered evidence as a numbered block for the prompt."""
    if not sources:
        return "(no external evidence found — judge from well-known facts and say so)"
    blocks = []
    for i, s in enumerate(sources, 1):
        title = (s.get("title") or "").strip()
        url = (s.get("url") or "").strip()
        snippet = (s.get("snippet") or "").strip()
        head = f"[{i}] {title} ({url})".strip()
        blocks.append(f"{head}\n{snippet}".strip())
    return "\n\n".join(blocks)


def build_prompt(prediction: dict, sources: list[dict], current_date: str) -> str:
    """Assemble the single-prediction, evidence-grounded verdict prompt."""
    return BACKFILL_PROMPT.format(
        prediction_date=prediction.get("prediction_date") or prediction.get("article_date", "unknown"),
        current_date=current_date,
        topic=prediction.get("topic", ""),
        claim=prediction.get("claim", ""),
        evidence=format_evidence(sources),
    )


def parse_verdict(text: str) -> dict | None:
    """Extract a ``{verdict, reasoning, confidence, sources}`` object from a model reply.

    Tolerates prose and markdown fences around the JSON. Returns ``None`` if no valid
    object with a recognized verdict can be found.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    verdict = obj.get("verdict")
    if verdict not in VALID_VERDICTS:
        return None
    confidence = obj.get("confidence", "low")
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"
    reasoning = obj.get("reasoning") or obj.get("verdict_reasoning") or ""
    sources = obj.get("sources")
    if not isinstance(sources, list):
        sources = []
    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "confidence": confidence,
        "sources": sources,
    }


def normalize_sources(sources: list) -> list[dict]:
    """Reduce gathered evidence to compact ``{title, url}`` receipts for storage."""
    out = []
    for s in sources:
        if isinstance(s, dict):
            out.append({"title": s.get("title", ""), "url": s.get("url", "")})
        elif isinstance(s, str):
            out.append({"title": "", "url": s})
    return out


def needs_backfill(prediction: dict) -> bool:
    """True if this prediction has no evidence-grounded verdict yet."""
    return not prediction.get("evidence_verdict")


def augment_prediction(
    prediction: dict,
    sources: list[dict],
    chat: Callable[[str], str],
    *,
    current_date: str | None = None,
    now: str | None = None,
) -> dict | None:
    """Run the grounded verdict for one prediction, writing back ``evidence_*`` fields.

    Returns the mutated prediction on success, or ``None`` (writing nothing) if the model
    reply could not be parsed. Advisory ``llm_*`` and authoritative ``human_*`` fields are
    never touched — the grounded verdict is an additional advisory layer.
    """
    current_date = current_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = build_prompt(prediction, sources, current_date)
    parsed = parse_verdict(chat(prompt))
    if parsed is None:
        return None
    prediction["evidence_verdict"] = parsed["verdict"]
    prediction["evidence_verdict_reasoning"] = parsed["reasoning"]
    prediction["evidence_verdict_confidence"] = parsed["confidence"]
    prediction["evidence_sources"] = normalize_sources(sources)
    prediction["evidence_verdict_at"] = now or datetime.now(timezone.utc).isoformat()
    return prediction


def run_backfill(
    predictions: list[dict],
    gather_evidence: Callable[[dict], list[dict]],
    chat: Callable[[str], str],
    *,
    save: Callable[[], None] | None = None,
    save_every: int = 10,
    limit: int | None = None,
    current_date: str | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Run the grounded verdict pass over every prediction needing one.

    Mutates ``predictions`` in place. ``gather_evidence`` and ``chat`` are injected seams.
    If ``save`` is given it is invoked every ``save_every`` predictions and once at the end
    (only when work happened), so a long run survives interruption. Returns a summary dict.
    """
    targets = [p for p in predictions if needs_backfill(p)]
    if limit is not None:
        targets = targets[:limit]

    processed = 0
    failed = 0
    for i, prediction in enumerate(targets, 1):
        try:
            sources = gather_evidence(prediction)
        except Exception as exc:  # evidence is best-effort; verdict still proceeds
            log(f"  evidence gathering failed ({exc}); proceeding without it")
            sources = []
        result = augment_prediction(prediction, sources, chat, current_date=current_date)
        if result is None:
            failed += 1
            log(f"  [{i}/{len(targets)}] unparseable verdict — skipped")
        else:
            processed += 1
            log(f"  [{i}/{len(targets)}] {result['evidence_verdict']}")
        if save is not None and i % save_every == 0:
            save()
            log(f"    [checkpoint after {i}]")

    if save is not None and processed:
        save()
    return {"targets": len(targets), "processed": processed, "failed": failed}


# --------------------------------------------------------------------------- #
# CLI wiring (owner-gated; makes real paid calls — not for automation)
# --------------------------------------------------------------------------- #

def _conductor_up(url: str = "http://127.0.0.1:8080/v1") -> bool:
    """Best-effort reachability check for the local conductor."""
    import urllib.error
    from urllib.request import urlopen

    try:
        with urlopen(url.rstrip("/") + "/models", timeout=4) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _conductor_chat(tier: int = 3) -> Callable[[str], str]:
    """A ``chat`` seam backed by the conductor (defaults to paid tier 3)."""
    from .predictions import _call, _get_client

    client = _get_client()

    def chat(prompt: str) -> str:
        return _call(client, prompt, max_tokens=1024, tier=tier)

    return chat


def _evidence_from_file(path: Path) -> Callable[[dict], list[dict]]:
    """Owner-supplied evidence: a JSON object mapping claim text -> list of source dicts.

    Lets the family run a fully deterministic, offline grounded pass by curating evidence
    by hand. Predictions absent from the file get no evidence.
    """
    mapping = json.loads(Path(path).read_text())

    def gather(prediction: dict) -> list[dict]:
        return mapping.get(prediction.get("claim", ""), [])

    return gather


def _no_evidence(_prediction: dict) -> list[dict]:
    """Default evidence seam: none. The model rules from its own knowledge.

    A real web-search provider is the owner's integration step — confirm the conductor's
    search contract (or wire an external search API) before relying on it.
    """
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.verdict_backfill",
        description="Evidence-augmented verdict backfill for Track Record predictions. "
                    "Owner-gated: makes paid T3 calls, so it refuses to run if the "
                    "conductor is down.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_PATH,
                        help="predictions.json (default: data/analysis/predictions.json)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Backfill at most N predictions this run.")
    parser.add_argument("--evidence-file", type=Path, default=None,
                        help="JSON map of claim -> [source dicts] for offline grounding.")
    parser.add_argument("--save-every", type=int, default=10,
                        help="Checkpoint to disk every N predictions (default: 10).")
    parser.add_argument("--tier", type=int, default=3,
                        help="Conductor tier for the verdict call (default: 3, paid).")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"No predictions file at {args.input}. Run `make analyze` first.")
        return 1

    if not _conductor_up():
        print("Conductor is unreachable at http://127.0.0.1:8080 — start it before "
              "running the backfill (this pass makes paid T3 calls). Aborting.")
        return 2

    data = json.loads(args.input.read_text())
    predictions = data.get("predictions", [])

    gather = _evidence_from_file(args.evidence_file) if args.evidence_file else _no_evidence
    chat = _conductor_chat(tier=args.tier)

    def save() -> None:
        args.input.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    start = time.time()
    summary = run_backfill(
        predictions, gather_evidence=gather, chat=chat,
        save=save, save_every=args.save_every, limit=args.limit,
    )
    print(f"\nBackfill done in {round(time.time() - start, 1)}s: "
          f"{summary['processed']} verdicts, {summary['failed']} failed, "
          f"{summary['targets']} targeted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
