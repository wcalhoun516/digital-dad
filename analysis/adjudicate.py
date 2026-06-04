"""Track Record adjudication — the human-override layer over advisory LLM verdicts.

The verdict pass in ``predictions.py`` produces an *advisory* ``llm_verdict`` for each
prediction but deliberately leaves ``status`` at ``pending`` — an LLM guess is not an
authoritative ruling on how Dr. Calhoun's bets turned out. This module lets the family
confirm or override those guesses by hand. A human ruling always wins.

Precedence for a prediction's effective verdict: ``human_verdict`` > ``llm_verdict`` >
``status`` > ``"pending"``. Adjudicating writes ``human_verdict`` (plus a free-text note
and timestamp), mirrors it into ``status``, and stamps ``verdict_source = "human"`` so the
dashboard can show who decided.

Run the interactive CLI with ``python -m analysis.adjudicate`` (or ``make adjudicate``).
It walks unadjudicated predictions and writes back after each one, so it is fully resumable.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .utils import DATA_DIR

VALID_VERDICTS = ("vindicated", "wrong", "mixed", "unfalsifiable", "pending")

DEFAULT_PATH = DATA_DIR / "analysis" / "predictions.json"

# Single-key shortcuts for the interactive prompt.
_KEYMAP = {
    "v": "vindicated",
    "w": "wrong",
    "m": "mixed",
    "u": "unfalsifiable",
    "p": "pending",
}


def effective_verdict(prediction: dict) -> str:
    """Resolve a prediction's effective verdict by precedence.

    human_verdict > llm_verdict > status > "pending". Empty/missing values are skipped.
    """
    for key in ("human_verdict", "llm_verdict", "status"):
        value = prediction.get(key)
        if value:
            return value
    return "pending"


def effective_source(prediction: dict) -> str:
    """Return who the effective verdict came from: "human", "llm", or "pending"."""
    if prediction.get("human_verdict"):
        return "human"
    if prediction.get("llm_verdict"):
        return "llm"
    return "pending"


def apply_adjudication(
    prediction: dict, verdict: str, note: str = "", now: str | None = None
) -> dict:
    """Record a human ruling on a prediction, mutating and returning it.

    The human verdict becomes authoritative: it is mirrored into ``status`` and
    ``verdict_source`` is set to ``"human"``. The advisory LLM fields are left intact.
    """
    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"invalid verdict {verdict!r}; expected one of {', '.join(VALID_VERDICTS)}"
        )
    prediction["human_verdict"] = verdict
    prediction["human_verdict_note"] = note
    prediction["human_verdict_at"] = now or datetime.now(timezone.utc).isoformat()
    prediction["status"] = verdict
    prediction["verdict_source"] = "human"
    return prediction


def iter_unadjudicated(predictions: Iterable[dict]) -> Iterator[dict]:
    """Yield predictions that have no human verdict yet."""
    for p in predictions:
        if not p.get("human_verdict"):
            yield p


def adjudication_summary(predictions: list[dict]) -> dict:
    """Tally progress and the effective-verdict distribution across all predictions."""
    by_verdict: dict[str, int] = {}
    adjudicated = 0
    for p in predictions:
        if p.get("human_verdict"):
            adjudicated += 1
        v = effective_verdict(p)
        by_verdict[v] = by_verdict.get(v, 0) + 1
    total = len(predictions)
    return {
        "total": total,
        "adjudicated": adjudicated,
        "pending_adjudication": total - adjudicated,
        "by_verdict": by_verdict,
    }


# Verdicts that count as "resolved" for calibration (a real outcome we can score).
_RESOLVED = ("vindicated", "wrong", "mixed")
_CONFIDENCE_BUCKETS = ("hedged", "confident", "certain")
_HIGH_CONVICTION = ("confident", "certain")
_CONVICTION_RANK = {"certain": 0, "confident": 1, "hedged": 2}


def calibration_report(predictions: list[dict]) -> dict:
    """Hit-rate by how confidently he phrased each call.

    For each confidence bucket, tally resolved effective verdicts and an accuracy score:
    ``(vindicated + 0.5 * mixed) / resolved``. Pending/unfalsifiable are not resolved and
    are excluded. Accuracy is ``None`` when a bucket has nothing resolved.
    """
    by_confidence = {
        b: {"vindicated": 0, "wrong": 0, "mixed": 0, "resolved": 0, "accuracy": None}
        for b in _CONFIDENCE_BUCKETS
    }
    resolved_total = 0
    for p in predictions:
        bucket = by_confidence.get(p.get("confidence_language"))
        if bucket is None:
            continue
        v = effective_verdict(p)
        if v not in _RESOLVED:
            continue
        bucket[v] += 1
        bucket["resolved"] += 1
        resolved_total += 1
    for bucket in by_confidence.values():
        if bucket["resolved"]:
            score = bucket["vindicated"] + 0.5 * bucket["mixed"]
            bucket["accuracy"] = round(score / bucket["resolved"], 3)
    return {"by_confidence": by_confidence, "resolved_total": resolved_total}


def conviction_boards(predictions: list[dict], limit: int = 5) -> dict:
    """High-conviction hits and misses — bold calls (confident/certain) he nailed or blew.

    Returns ``{"most_right": [...], "most_wrong": [...]}``, each a list of compact prediction
    dicts sorted by conviction (certain before confident), capped at ``limit``.
    """
    def _board(target_verdict: str) -> list[dict]:
        rows = [
            p for p in predictions
            if p.get("confidence_language") in _HIGH_CONVICTION
            and effective_verdict(p) == target_verdict
        ]
        rows.sort(key=lambda p: _CONVICTION_RANK.get(p.get("confidence_language"), 9))
        return [
            {
                "claim": p.get("claim", ""),
                "topic": p.get("topic", ""),
                "confidence_language": p.get("confidence_language", ""),
                "article_date": p.get("article_date", ""),
                "article_url": p.get("article_url", ""),
            }
            for p in rows[:limit]
        ]

    return {"most_right": _board("vindicated"), "most_wrong": _board("wrong")}


def load_predictions(path: Path = DEFAULT_PATH) -> dict:
    """Load the predictions file as its full top-level dict."""
    return json.loads(Path(path).read_text())


def save_predictions(path: Path, data: dict) -> None:
    """Write the predictions file back, pretty-printed for reviewable diffs."""
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _prompt_verdict(prediction: dict) -> tuple[str, str] | None | str:
    """Show one prediction and read a ruling from stdin.

    Returns ``(verdict, note)`` to record, ``None`` to skip, or the string ``"quit"``.
    """
    claim = prediction.get("claim", "(no claim)")
    topic = prediction.get("topic", "?")
    pdate = prediction.get("prediction_date") or prediction.get("article_date", "?")
    title = prediction.get("article_title", "")
    llm = prediction.get("llm_verdict", "—")
    llm_reason = prediction.get("llm_verdict_reasoning") or ""

    print("\n" + "=" * 72)
    print(f"  [{pdate}] {topic}  ·  {title[:50]}")
    print(f"  CLAIM: {claim}")
    print(f"  LLM (advisory): {llm}"
          + (f" — {llm_reason}" if llm_reason else ""))
    print("-" * 72)
    print("  [v]indicated  [w]rong  [m]ixed  [u]nfalsifiable  [p]ending"
          "   ([s]kip / [q]uit)")
    choice = input("  verdict> ").strip().lower()

    if choice in ("q", "quit"):
        return "quit"
    if choice in ("s", "skip", ""):
        return None
    verdict = _KEYMAP.get(choice, choice)
    if verdict not in VALID_VERDICTS:
        print(f"  ! '{choice}' is not a valid verdict — skipping.")
        return None
    note = input("  note (optional)> ").strip()
    return verdict, note


def print_report(predictions: list[dict]) -> None:
    """Print the calibration report + conviction boards to stdout."""
    report = calibration_report(predictions)
    print("\nCalibration — accuracy by confidence language "
          "(vindicated + ½·mixed, over resolved):")
    for bucket in _CONFIDENCE_BUCKETS:
        row = report["by_confidence"][bucket]
        acc = "n/a" if row["accuracy"] is None else f"{row['accuracy']:.0%}"
        print(f"  {bucket:>9}: {acc:>4}  "
              f"(✓{row['vindicated']} ✗{row['wrong']} ~{row['mixed']}, "
              f"resolved {row['resolved']})")
    print(f"  resolved total: {report['resolved_total']}")

    boards = conviction_boards(predictions)
    for label, key in (("Bold calls he nailed", "most_right"),
                       ("Bold calls he missed", "most_wrong")):
        rows = boards[key]
        print(f"\n{label}:")
        if not rows:
            print("  (none yet)")
        for r in rows:
            print(f"  [{r['confidence_language']}] {r['claim'][:90]}")


def run_cli(path: Path = DEFAULT_PATH, limit: int | None = None) -> int:
    """Interactive adjudication loop. Writes back after every ruling (resumable)."""
    path = Path(path)
    if not path.exists():
        print(f"No predictions file at {path}. Run `make analyze` first.")
        return 1

    data = load_predictions(path)
    predictions = data.get("predictions", [])
    summary = adjudication_summary(predictions)
    print(f"Loaded {summary['total']} predictions — "
          f"{summary['adjudicated']} adjudicated, "
          f"{summary['pending_adjudication']} to go.")

    done = 0
    for prediction in iter_unadjudicated(predictions):
        if limit is not None and done >= limit:
            print(f"\nReached limit of {limit}. Stopping.")
            break
        result = _prompt_verdict(prediction)
        if result == "quit":
            break
        if result is None:
            continue
        verdict, note = result
        apply_adjudication(prediction, verdict, note=note)
        save_predictions(path, data)  # write back immediately so progress survives
        done += 1
        print(f"  ✓ recorded: {verdict}")

    final = adjudication_summary(predictions)
    print(f"\nDone. {final['adjudicated']}/{final['total']} adjudicated "
          f"this session: +{done}.")
    print_report(predictions)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.adjudicate",
        description="Confirm or override LLM verdicts on Track Record predictions.",
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_PATH,
        help="Path to predictions.json (default: data/analysis/predictions.json)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Adjudicate at most N predictions this session.",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Print the calibration report (hit-rate by confidence) and exit; adjudicate nothing.",
    )
    args = parser.parse_args(argv)
    if args.report:
        if not args.input.exists():
            print(f"No predictions file at {args.input}. Run `make analyze` first.")
            return 1
        print_report(load_predictions(args.input).get("predictions", []))
        return 0
    return run_cli(path=args.input, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
