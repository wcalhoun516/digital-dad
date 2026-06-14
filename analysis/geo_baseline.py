"""Geo-LLM baseline capture (plan 0008 step 26b / roadmap #26).

Freeze the pre-fine-tune numbers that any "Geo LLM" voice fine-tune must beat. This is a
deterministic *snapshot* of the #25 RAG faithfulness eval (plan 0007): it reads that
harness's already-written output (``data/analysis/rag_eval.json``) and curates it into
``data/analysis/geo_llm_baseline.json`` plus a short markdown note, with a ``voice`` slot
left pending for the 26d voice-fidelity harness.

It makes **no** conductor / paid T3 calls — the expensive judge pass happens in
``analysis.rag_eval`` (owner-gated). If ``rag_eval.json`` is missing, this tool tells the
owner to run ``make rag-eval`` first and exits without writing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAG_EVAL_PATH = DATA_DIR / "analysis" / "rag_eval.json"
BASELINE_PATH = DATA_DIR / "analysis" / "geo_llm_baseline.json"
BASELINE_NOTE_PATH = ROOT_DIR / "docs" / "geo_llm_baseline.md"

HIGHER_IS_BETTER = "higher_is_better"
LOWER_IS_BETTER = "lower_is_better"

# The faithfulness metrics a fine-tune must not regress on, and which way is "better".
# (citation_coverage is RAG-specific — a retrieval-free fine-tune can't cite retrieved
# titles — so it's recorded under factuality but is not a hard target.)
TARGET_METRICS = {
    "grounding_rate": HIGHER_IS_BETTER,
    "hallucination_rate": LOWER_IS_BETTER,
    "abstention_accuracy": HIGHER_IS_BETTER,
    "false_abstention_rate": LOWER_IS_BETTER,
}

# Summary keys that are fractions (rendered as percentages in the note).
_RATE_KEYS = {
    "grounding_rate",
    "hallucination_rate",
    "abstention_accuracy",
    "false_abstention_rate",
    "citation_coverage",
}

_FACTUALITY_KEYS = [
    "n_questions",
    "n_answerable",
    "n_unanswerable",
    "total_claims",
    "grounded_claims",
    "grounding_rate",
    "hallucination_rate",
    "abstention_accuracy",
    "false_abstention_rate",
    "citation_coverage",
]


def load_rag_summary(path: Path = RAG_EVAL_PATH) -> dict | None:
    """Return the full ``rag_eval.json`` object, or ``None`` if missing/malformed."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def build_baseline(rag_eval: dict, *, captured_at: str | None = None) -> dict:
    """Shape a #25 RAG eval result into the curated 'bar to beat' baseline artifact.

    ``rag_eval`` is the full ``{generated_at, summary, ...}`` object. The returned dict
    carries the factuality numbers, a machine-readable ``targets`` block (direction +
    the value a fine-tune must beat), provenance, and a pending ``voice`` slot.
    """
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat()
    summary = rag_eval.get("summary", {})

    factuality = {k: summary[k] for k in _FACTUALITY_KEYS if k in summary}
    targets = {
        metric: {
            "baseline": summary[metric],
            "direction": direction,
            "must_beat": summary[metric],
        }
        for metric, direction in TARGET_METRICS.items()
        if metric in summary
    }

    return {
        "description": (
            "Pre-fine-tune baseline for the Geo LLM (#26). These are the numbers any "
            "fine-tuned George-Calhoun-voice model must beat on faithfulness; the voice "
            "half is filled in by the 26d voice-fidelity harness."
        ),
        "captured_at": captured_at,
        "source": {
            "harness": "analysis.rag_eval (#25, plan 0007)",
            "rag_eval_generated_at": rag_eval.get("generated_at"),
            "n_questions": summary.get("n_questions"),
        },
        "factuality": factuality,
        "voice": {
            "status": "pending",
            "note": "Populated by the 26d voice-fidelity eval harness (blind A/B vs RAG and real excerpts).",
        },
        "targets": targets,
    }


def compare_to_targets(baseline: dict, candidate: dict) -> dict:
    """Score a candidate model's metrics against the baseline's must-beat targets.

    ``candidate`` is a flat ``{metric: value}`` dict (e.g. a later run's summary). For
    each target a fine-tune must **beat** (strictly — matching the bar is not beating it)
    in the right direction. A metric the candidate didn't report can't be claimed as a
    win, so it lands in ``missing`` and forces ``all_passed`` False. Pure: 26d/26f reuse
    this to decide fine-tune vs RAG without re-deriving the comparison.
    """
    per_metric: dict[str, dict] = {}
    missing: list[str] = []
    for metric, target in baseline.get("targets", {}).items():
        if metric not in candidate:
            missing.append(metric)
            continue
        base = target["baseline"]
        cand = candidate[metric]
        if target["direction"] == HIGHER_IS_BETTER:
            passed = cand > base
        else:
            passed = cand < base
        per_metric[metric] = {
            "baseline": base,
            "candidate": cand,
            "delta": cand - base,
            "passed": passed,
        }
    all_passed = bool(per_metric) and not missing and all(m["passed"] for m in per_metric.values())
    return {"per_metric": per_metric, "missing": missing, "all_passed": all_passed}


def _pct(value) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(baseline: dict) -> str:
    """Render the baseline as a short human-readable note."""
    f = baseline["factuality"]
    src = baseline["source"]
    gen = (src.get("rag_eval_generated_at") or "")[:10] or "unknown"

    lines = [
        "# Geo LLM — pre-fine-tune baseline (26b)",
        "",
        baseline["description"],
        "",
        f"- **Captured:** {baseline['captured_at'][:10]}",
        f"- **Source:** {src['harness']}, run {gen} "
        f"({src.get('n_questions')} held-out questions)",
        "",
        "## Factuality (RAG / Ask Dad) — the bar to beat",
        "",
        "| Metric | Baseline | Better |",
        "| --- | --- | --- |",
    ]
    direction_label = {HIGHER_IS_BETTER: "higher ↑", LOWER_IS_BETTER: "lower ↓"}
    for metric in _FACTUALITY_KEYS:
        if metric not in f:
            continue
        val = _pct(f[metric]) if metric in _RATE_KEYS else str(f[metric])
        target = baseline["targets"].get(metric)
        better = direction_label[target["direction"]] if target else "—"
        lines.append(f"| `{metric}` | {val} | {better} |")

    lines += [
        "",
        "A fine-tune must **beat** (not merely match) these on the four targeted "
        "faithfulness metrics to justify replacing RAG. `citation_coverage` is "
        "RAG-specific and informational only.",
        "",
        "## Voice fidelity",
        "",
        f"_{baseline['voice']['status']}_ — {baseline['voice']['note']}",
        "",
    ]
    return "\n".join(lines)


def run():
    rag_eval = load_rag_summary()
    if rag_eval is None or not rag_eval.get("summary"):
        print(
            f"No usable RAG eval found at {RAG_EVAL_PATH}.\n"
            "Run `make rag-eval` first (owner-gated; needs the conductor) to capture the "
            "#25 baseline, then re-run `make geo-baseline`."
        )
        return

    baseline = build_baseline(rag_eval)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")
    BASELINE_NOTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_NOTE_PATH.write_text(render_markdown(baseline) + "\n")

    s = baseline["factuality"]
    print(f"Geo LLM baseline captured -> {BASELINE_PATH}")
    print(
        f"  grounding {_pct(s['grounding_rate'])}, hallucination {_pct(s['hallucination_rate'])}, "
        f"abstention {_pct(s['abstention_accuracy'])}, "
        f"false-abstention {_pct(s['false_abstention_rate'])}."
    )
    print(f"  note -> {BASELINE_NOTE_PATH}")


if __name__ == "__main__":
    run()
