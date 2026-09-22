"""The scoreboard: did this run beat the last one? (plan 0011 step 5)

Geo-LLM stalled because it was a one-shot experiment that failed once and was shelved
by an ADR — nobody could see whether a change helped. A flywheel needs a dial. This
module is that dial's arithmetic: it reads the reports the eval harnesses already
write, lines the newest run up against the one before it and against D15's standing
baseline, and says which way each number moved.

Three sources, none of which this module computes itself:

- ``analysis.voice_eval`` → ``data/analysis/voice_eval.json`` — win-rate and average
  rank per source, plus the style block's type-token ratio and hinge-word rate.
- ``analysis.rag_eval`` → ``data/analysis/rag_eval.json`` — grounding, abstention and
  citation coverage.
- ``training.finetune_preflight`` → the length-budget check's ``pct_over``. It writes
  no file of its own, so the caller passes the report in.

The run series comes from ``analysis.voice_candidates.history_rows`` — the append-only
``voice_eval_history.jsonl`` that already exists, one row per *arm* per run. A second
history would be a second implementation of the same record, so there isn't one.

Every reader is total: a report the operator has never generated is an absence, and a
half-written one is the same absence. The scoreboard's whole job is to be readable on
a machine where most of the pipeline has never been run.
"""

import argparse
import json
from pathlib import Path

from .utils import DATA_DIR

VOICE_REPORT_PATH = DATA_DIR / "analysis" / "voice_eval.json"
RAG_REPORT_PATH = DATA_DIR / "analysis" / "rag_eval.json"

# Ranking metrics live directly on `summary.sources[src]`; style metrics live one
# level down on `summary.style.sources[src].mean`. Both are optional — `voice-eval`
# without `voice-style` yields the first, `make voice-style` alone yields the second.
_RANK_KEYS = ("win_rate", "avg_rank", "appearances", "wins")
_STYLE_KEYS = (
    "type_token_ratio",
    "fingerprint_hits_per_1k",
    "avg_sentence_len",
    "word_count",
)
_RAG_KEYS = (
    "grounding_rate",
    "hallucination_rate",
    "abstention_accuracy",
    "false_abstention_rate",
    "citation_coverage",
    "n_questions",
)
_PREFLIGHT_KEYS = ("pct_over", "n_over", "n", "max_seq_len", "ok")

# Which way is better is a property of the metric. Without this the scoreboard can
# only show a signed number, and two of these numbers mean the opposite of what a
# reader would assume:
#
# ``toward`` metrics have a right answer rather than a direction. D15's finding was
# that the fine-tune used his distinctive vocabulary at ~2x the natural rate (101 vs
# 46 hits/1k) — scoring that "lower is better" would reward a model that had lost his
# vocabulary altogether, and scoring it "higher is better" would reward the parody.
# The target is the real corpus, and the move that counts is closing the gap.
DIRECTIONS = {
    "win_rate": "higher",
    "avg_rank": "lower",
    "type_token_ratio": "toward",
    "fingerprint_hits_per_1k": "toward",
    "avg_sentence_len": "toward",
    "grounding_rate": "higher",
    "hallucination_rate": "lower",
    "abstention_accuracy": "higher",
    "false_abstention_rate": "lower",
    "citation_coverage": "higher",
    "pct_over": "lower",
}

# The standing baseline: D15's blind voice-fidelity eval, the record every later run
# is read against. See docs/decisions.md § D15.
BASELINE = {
    "adr": "D15",
    "note": (
        "8 held-out prompts, T3 judge: the fine-tune placed last in every trial while "
        "RAG and the real excerpts tied at the top."
    ),
    "voice": {
        "finetune": {
            "win_rate": 0.0,
            "avg_rank": 2.88,
            "type_token_ratio": 0.35,
            "fingerprint_hits_per_1k": 101.0,
        },
        "rag": {"avg_rank": 1.50},
        "real": {
            "avg_rank": 1.63,
            "type_token_ratio": 0.70,
            "fingerprint_hits_per_1k": 46.0,
        },
    },
}


def compare(metric: str, current, previous, target=None) -> dict:
    """Score one metric's move, labelled ``better``/``worse``/``flat``.

    ``unknown`` means there is nothing to compare against yet; ``unscored`` means the
    move is real but this module will not claim a direction for it — an unrecognised
    metric, or a ``toward`` metric with no target to aim at. Both are reported rather
    than hidden, because a silently dropped metric reads as a metric that did not move.
    """
    result = {
        "metric": metric,
        "current": current,
        "previous": previous,
        "delta": None,
        "verdict": "unknown",
    }
    direction = DIRECTIONS.get(metric)
    if direction == "toward":
        result["target"] = target
        if target is not None and current is not None:
            result["gap"] = abs(current - target)
    if current is None or previous is None:
        return result
    result["delta"] = round(current - previous, 6)

    if direction == "toward":
        if target is None:
            result["verdict"] = "unscored"
            return result
        moved = round(abs(current - target) - abs(previous - target), 6)
        result["verdict"] = "flat" if moved == 0 else ("better" if moved < 0 else "worse")
        return result

    if direction is None:
        result["verdict"] = "unscored"
        return result
    if result["delta"] == 0:
        result["verdict"] = "flat"
        return result
    rose = result["delta"] > 0
    result["verdict"] = "better" if rose == (direction == "higher") else "worse"
    return result


def read_report(path) -> dict | None:
    """A ``{generated_at, summary, records}`` report, or ``None`` if there isn't one.

    Absent, unreadable, malformed and summary-less all collapse to ``None``: the
    operator's question is "has this been run?", and every one of those answers no.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        return None
    return payload


def voice_scores(report: dict | None) -> dict:
    """One flat row of metrics per source in a ``voice_eval`` report.

    Sources are the union of the ranking block and the style block, so an arm that
    was style-scored but never judged still appears — with only the keys it has.
    """
    if not report:
        return {}
    summary = report.get("summary") or {}
    ranked = summary.get("sources") or {}
    styled = ((summary.get("style") or {}).get("sources")) or {}

    scores: dict[str, dict] = {}
    for source in sorted(set(ranked) | set(styled)):
        row: dict = {}
        for key in _RANK_KEYS:
            value = (ranked.get(source) or {}).get(key)
            if value is not None:
                row[key] = value
        for key in _STYLE_KEYS:
            value = ((styled.get(source) or {}).get("mean") or {}).get(key)
            if value is not None:
                row[key] = value
        scores[source] = row
    return scores


def rag_scores(report: dict | None) -> dict:
    """The faithfulness headlines from a ``rag_eval`` report."""
    if not report:
        return {}
    summary = report.get("summary") or {}
    return {k: summary[k] for k in _RAG_KEYS if k in summary}


def preflight_scores(report: dict | None) -> dict:
    """The length-budget check from a ``finetune_preflight`` report.

    ``pct_over`` is the number that matters: records over ``max_seq_len`` are dropped
    or truncated by mlx-lm, which is the quietest way a run trains on almost nothing.
    """
    if not report:
        return {}
    budget = ((report.get("checks") or {}).get("length_budget")) or {}
    return {k: budget[k] for k in _PREFLIGHT_KEYS if k in budget}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice-report", type=Path, default=VOICE_REPORT_PATH)
    parser.add_argument("--rag-report", type=Path, default=RAG_REPORT_PATH)
    args = parser.parse_args(argv)

    payload = {
        "voice": voice_scores(read_report(args.voice_report)),
        "rag": rag_scores(read_report(args.rag_report)),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
