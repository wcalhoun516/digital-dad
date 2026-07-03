"""Voice-fidelity eval harness for the Geo-LLM fine-tune (plan 0008 step 26d).

Answers the question 26 ultimately turns on: does a small local fine-tune write in
Dr. George Calhoun's voice *better than* the existing RAG ("Ask Dad"), and how close
does either get to his real prose? It does this with a **blind A/B(/C) ranking**: for
each held-out prompt the harness collects candidate passages from different sources
(`real` excerpt, `rag` answer, `finetuned` answer), anonymizes them to labels A/B/C so
the judge can't tell which is which, asks a strong judge model to rank them by how much
they read like Calhoun, then un-blinds and aggregates win-rates per source.

Following ``analysis.rag_eval``, the networked part is isolated behind a single injected
seam so all scoring logic is unit-testable offline:

- ``judge(prompt, blinded) -> list[str]`` — returns a ranking of the anonymized labels
  (best→worst). The live implementation prompts the conductor (paid T3) and parses the
  reply with ``parse_ranking``.

The blinding, ranking parser, un-blinding, run loop, and aggregation are pure functions;
the CLI (``python -m analysis.voice_eval`` / ``make voice-eval``) wires the seam to the
live conductor and is gated on its reachability because a live pass makes paid T3 calls.

Alongside the judge ranking there is a **deterministic style companion**: each candidate
passage is scored with ``training.finetune_config.style_metrics`` (type-token ratio, avg
sentence length, Calhoun-fingerprint hit rate vs ``data/analysis/linguistics.json``) and
aggregated per source with a delta-vs-``real``. It is judge-independent, so it runs offline
with no paid calls — ``--style-only`` / ``make voice-style`` produces it even when the
conductor is down, and the judged report folds it in too.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Hashable

from training.finetune_config import style_metrics

from .conductor import require_conductor
from .utils import DATA_DIR

# Repo-root-relative fixture template (the real trials are owner-produced once the 26c
# adapter exists and are not committed — see eval/voice_trials.example.json).
TRIALS_PATH = Path(__file__).resolve().parent.parent / "eval" / "voice_trials.json"
REPORT_PATH = DATA_DIR / "analysis" / "voice_eval.json"
STYLE_REPORT_PATH = DATA_DIR / "analysis" / "voice_style.json"
LINGUISTICS_PATH = DATA_DIR / "analysis" / "linguistics.json"

DEFAULT_SEED = 1337
# How many of the corpus's distinctive words count as the "Calhoun fingerprint";
# matches the 26c notebook so the notebook and this eval score style the same way.
DEFAULT_FINGERPRINT_WORDS = 30

STYLE_METRIC_KEYS = (
    "word_count",
    "type_token_ratio",
    "avg_sentence_len",
    "fingerprint_hits_per_1k",
)


# --------------------------------------------------------------------------- #
# Blinding + ranking helpers (pure)
# --------------------------------------------------------------------------- #

def _labels(n: int) -> list[str]:
    """The first *n* uppercase-letter labels: A, B, C, ..."""
    return [chr(ord("A") + i) for i in range(n)]


def blind_candidates(
    candidates: dict[str, str], *, seed: Hashable = DEFAULT_SEED
) -> tuple[dict[str, str], dict[str, str]]:
    """Anonymize *candidates* (``{source: text}``) to labelled passages.

    Returns ``(blinded, mapping)`` where ``blinded`` is ``{label: text}`` and ``mapping``
    is ``{label: source}``. Sources are sorted first so the only randomness is a seeded
    shuffle, making the assignment deterministic per *seed* (and so auditable) while still
    varying which label a given source lands on across seeds.
    """
    sources = sorted(candidates)
    random.Random(seed).shuffle(sources)
    labels = _labels(len(sources))
    mapping = dict(zip(labels, sources))
    blinded = {label: candidates[source] for label, source in mapping.items()}
    return blinded, mapping


def build_judge_prompt(prompt: str, blinded: dict[str, str]) -> str:
    """Construct the blind-ranking instruction for the judge model."""
    passages = "\n\n".join(
        f"[{label}]\n{text}" for label, text in sorted(blinded.items())
    )
    labels = ", ".join(sorted(blinded))
    return _JUDGE_PROMPT.format(prompt=prompt, passages=passages, labels=labels)


def parse_ranking(text: str, labels: list[str]) -> list[str] | None:
    """Extract the judge's ``{"ranking": [...]}`` ordering of *labels* from a reply.

    Tolerates prose/markdown fences around the JSON (like
    ``rag_eval.parse_judgment``). Unknown labels are dropped, duplicates collapse to
    their first appearance, and any *labels* the judge omitted are appended in their
    canonical order so the returned ranking is always total. Returns ``None`` if no
    JSON object with a list ``ranking`` can be found.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, AttributeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("ranking"), list):
        return None

    valid = set(labels)
    ordered: list[str] = []
    for item in obj["ranking"]:
        if item in valid and item not in ordered:
            ordered.append(item)
    for label in labels:
        if label not in ordered:
            ordered.append(label)
    return ordered


def unblind_ranking(ranking: list[str], mapping: dict[str, str]) -> list[str]:
    """Translate a ranking of anonymized labels back to source names."""
    return [mapping[label] for label in ranking]


# --------------------------------------------------------------------------- #
# Harness (injected seam) + aggregation (pure)
# --------------------------------------------------------------------------- #

def evaluate(
    trials: list[dict],
    judge: Callable[[str, dict[str, str]], list[str] | None],
    *,
    seed: Hashable = DEFAULT_SEED,
    distinctive_words: set | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Blind-rank each trial's candidates via *judge*; return per-trial rows.

    Each trial blinds its candidates with a per-trial seed derived from *seed* and the
    trial id, so the A/B/C assignment varies between trials but stays reproducible. A
    judge that returns ``None`` (unparseable) yields an empty ranking rather than
    aborting the run.

    When *distinctive_words* is given, each record also carries a ``style`` map
    (``{source: style_metrics}``) — the deterministic, judge-independent companion to
    the blind ranking (plan 0008 step 26d).
    """
    records: list[dict] = []
    for i, trial in enumerate(trials, 1):
        prompt = trial.get("prompt", "")
        candidates = trial.get("candidates", {})
        blinded, mapping = blind_candidates(
            candidates, seed=f"{seed}:{trial.get('id', i)}"
        )
        labels = judge(prompt, blinded)
        if labels is None:
            ranking: list[str] = []
        else:
            ranking = unblind_ranking([lbl for lbl in labels if lbl in mapping], mapping)
        record = {
            "id": trial.get("id"),
            "prompt": prompt,
            "sources": sorted(candidates),
            "blinding": mapping,
            "ranking": ranking,
            "winner": ranking[0] if ranking else None,
        }
        if distinctive_words is not None:
            record["style"] = trial_style(trial, distinctive_words)
        records.append(record)
        log(f"  [{i}/{len(trials)}] {trial.get('id')}: "
            f"{'/'.join(ranking) if ranking else 'unjudged'}")
    return records


# --------------------------------------------------------------------------- #
# Deterministic style companion (judge-independent) — plan 0008 step 26d
# --------------------------------------------------------------------------- #

def load_distinctive_words(
    path: Path = LINGUISTICS_PATH, top_n: int = DEFAULT_FINGERPRINT_WORDS
) -> set[str]:
    """Load the top-*n* distinctive corpus words (the "Calhoun fingerprint").

    Reads ``data/analysis/linguistics.json`` (``analysis.linguistic``'s output), the
    same source the 26c notebook uses. Returns an empty set if the file is absent or
    malformed so the style pass still runs (fingerprint rate just reads 0).
    """
    try:
        data = json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    words = data.get("distinctive_words", [])
    return {w["word"] for w in words[:top_n] if isinstance(w, dict) and "word" in w}


def trial_style(trial: dict, distinctive_words: set) -> dict[str, dict]:
    """Compute ``style_metrics`` for every candidate passage in *trial*."""
    return {
        source: style_metrics(text, distinctive_words)
        for source, text in trial.get("candidates", {}).items()
    }


def evaluate_style(trials: list[dict], distinctive_words: set) -> list[dict]:
    """Per-trial deterministic style rows (no judge / conductor needed)."""
    return [
        {
            "id": trial.get("id"),
            "prompt": trial.get("prompt", ""),
            "sources": sorted(trial.get("candidates", {})),
            "style": trial_style(trial, distinctive_words),
        }
        for trial in trials
    ]


def aggregate_style(records: list[dict]) -> dict:
    """Per-source mean style metrics + each non-real source's delta vs ``real``.

    Reads ``record["style"]`` (``{source: metrics}``); records without it are skipped.
    ``delta_vs_real`` is averaged per-trial over trials where the source and ``real``
    co-appear, so a deterministic "how far from his actual prose" signal survives even
    when the paid judge never runs.
    """
    styled = [r["style"] for r in records if isinstance(r.get("style"), dict)]
    sources = sorted({s for st in styled for s in st})

    per_source: dict[str, dict] = {}
    for source in sources:
        rows = [st[source] for st in styled if source in st]
        mean = {
            k: round(sum(m[k] for m in rows) / len(rows), 3) for k in STYLE_METRIC_KEYS
        }
        entry: dict = {"appearances": len(rows), "mean": mean}
        if source != "real":
            paired = [st for st in styled if source in st and "real" in st]
            if paired:
                entry["delta_vs_real"] = {
                    k: round(
                        sum(st[source][k] - st["real"][k] for st in paired) / len(paired),
                        3,
                    )
                    for k in STYLE_METRIC_KEYS
                }
        per_source[source] = entry

    return {"n_trials": len(styled), "sources": per_source}


def _style_table(summary: dict) -> list[str]:
    """The intro line + markdown table for an :func:`aggregate_style` result.

    Returns ``[]`` when there are no scored sources, so callers can decide whether to
    emit a section at all.
    """
    sources = summary.get("sources", {})
    if not sources:
        return []
    lines = [
        f"{summary.get('n_trials', 0)} trial(s); judge-independent companion to the "
        "blind A/B ranking (plan 0008 step 26d). `real` is the reference.",
        "",
        "| source | words | TTR | avg sent len | fingerprint/1k | Δ fingerprint vs real |",
        "|--------|-------|-----|--------------|----------------|-----------------------|",
    ]
    for source in sorted(sources):
        m = sources[source]["mean"]
        delta = sources[source].get("delta_vs_real", {})
        d_fp = delta.get("fingerprint_hits_per_1k")
        d_str = "—" if source == "real" or d_fp is None else f"{d_fp:+.1f}"
        lines.append(
            f"| {source} | {m['word_count']:.0f} | {m['type_token_ratio']:.3f} | "
            f"{m['avg_sentence_len']:.1f} | {m['fingerprint_hits_per_1k']:.1f} | {d_str} |"
        )
    lines.append("")
    return lines


def render_style_markdown(summary: dict) -> str:
    """Human-readable table of an :func:`aggregate_style` result."""
    table = _style_table(summary)
    header = ["# Geo-LLM voice — deterministic style metrics", ""]
    if not table:
        return "\n".join(header + ["No style metrics (no candidate passages with text)."])
    return "\n".join(header + table)


def write_style_report(records: list[dict], path: Path = STYLE_REPORT_PATH) -> dict:
    """Write ``{generated_at, summary, records}`` JSON; return the style summary."""
    summary = aggregate_style(records)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return summary


def aggregate(records: list[dict]) -> dict:
    """Win-rate, average rank, and head-to-head matrix per source.

    - ``win_rate`` — fraction of judged trials a source ranked #1 (the headline:
      does the fine-tune win the most blind comparisons?).
    - ``avg_rank`` — mean 1-indexed position (lower is better).
    - ``pairwise`` — ``"<a>_over_<b>"`` = fraction of trials where *a* outranked *b*,
      over trials that contain both (so RAG-vs-fine-tune isn't diluted by the real
      excerpt).
    """
    judged = [r for r in records if r.get("ranking")]
    sources: list[str] = sorted({s for r in judged for s in r["ranking"]})

    per_source: dict[str, dict] = {}
    for source in sources:
        ranks = [r["ranking"].index(source) + 1 for r in judged if source in r["ranking"]]
        wins = sum(1 for r in judged if r["ranking"] and r["ranking"][0] == source)
        appearances = len(ranks)
        per_source[source] = {
            "appearances": appearances,
            "wins": wins,
            "win_rate": round(wins / appearances, 4) if appearances else 0.0,
            "avg_rank": round(sum(ranks) / appearances, 4) if appearances else 0.0,
        }

    pairwise: dict[str, float] = {}
    for a in sources:
        for b in sources:
            if a == b:
                continue
            both = [r for r in judged if a in r["ranking"] and b in r["ranking"]]
            if not both:
                continue
            a_over_b = sum(
                1 for r in both if r["ranking"].index(a) < r["ranking"].index(b)
            )
            pairwise[f"{a}_over_{b}"] = round(a_over_b / len(both), 4)

    summary = {
        "n_trials": len(records),
        "n_judged": len(judged),
        "sources": per_source,
        "pairwise": pairwise,
    }
    if any(isinstance(r.get("style"), dict) for r in records):
        summary["style"] = aggregate_style(records)
    return summary


def render_markdown(summary: dict) -> str:
    """Human-readable summary of an :func:`aggregate` result (companion to the JSON)."""
    lines = [
        "# Geo-LLM voice-fidelity eval",
        "",
        f"{summary['n_judged']}/{summary['n_trials']} judged "
        "(blind A/B/C ranking by a T3 judge; plan 0008 step 26d).",
        "",
    ]
    sources = summary.get("sources", {})
    if sources:
        lines += [
            "| source | win-rate | avg rank | wins | appearances |",
            "|--------|----------|----------|------|-------------|",
        ]
        for source in sorted(sources, key=lambda s: sources[s]["avg_rank"]):
            s = sources[source]
            lines.append(
                f"| {source} | {s['win_rate']:.0%} | {s['avg_rank']:.2f} | "
                f"{s['wins']} | {s['appearances']} |"
            )
        lines.append("")
    pairwise = summary.get("pairwise", {})
    if pairwise:
        lines.append("## Head-to-head (fraction of shared trials the first source won)")
        lines.append("")
        for key in sorted(pairwise):
            lines.append(f"- `{key}`: {pairwise[key]:.0%}")
        lines.append("")
    style_table = _style_table(summary.get("style", {}))
    if style_table:
        lines.append("## Deterministic style metrics (judge-independent)")
        lines.append("")
        lines += style_table
    return "\n".join(lines)


def write_report(records: list[dict], path: Path = REPORT_PATH) -> dict:
    """Write ``{generated_at, summary, records}`` JSON; return the summary."""
    summary = aggregate(records)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return summary


def load_trials(path: Path = TRIALS_PATH) -> list[dict]:
    """Load the voice-eval trial set (prompt + per-source candidate passages)."""
    data = json.loads(Path(path).read_text())
    return data.get("trials", [])


# --------------------------------------------------------------------------- #
# Live seam (conductor) + CLI — owner-gated; makes paid T3 calls
# --------------------------------------------------------------------------- #

_JUDGE_PROMPT = """You are a literary judge scoring how closely passages match the voice of Dr. George Calhoun — a Forbes columnist and economist: contrarian, data-driven, rhetorically punchy, fond of historical analogy and pointed first-person argument.

You are given a PROMPT and several candidate PASSAGES, each labelled. Rank the passages from MOST to LEAST like Dr. Calhoun's authentic writing voice. Judge voice and style, not whether you agree with the content.

Return ONLY a JSON object (no markdown, no commentary):
{{
  "ranking": [<labels {labels} ordered best-voice first>]
}}

PROMPT
{prompt}

PASSAGES
{passages}"""


def _live_judge(tier: int = 3) -> Callable[[str, dict[str, str]], list[str] | None]:
    from .predictions import _call, _get_client

    client = _get_client()

    def judge(prompt: str, blinded: dict[str, str]) -> list[str] | None:
        reply = _call(client, build_judge_prompt(prompt, blinded), max_tokens=200, tier=tier)
        return parse_ranking(reply, sorted(blinded))

    return judge


def _run_style_only(args, distinctive: set) -> int:
    """Offline deterministic style pass (no conductor, no paid calls)."""
    if not distinctive:
        print("Note: no distinctive words loaded (run `python -m analysis linguistic` "
              "first) — fingerprint rate will read 0; other metrics are unaffected.")
    trials = load_trials(args.trials)
    records = evaluate_style(trials, distinctive)
    out = args.output if args.output != REPORT_PATH else STYLE_REPORT_PATH
    summary = write_style_report(records, out)
    note_path = out.with_suffix(".md")
    note_path.write_text(render_style_markdown(summary) + "\n")
    print(render_style_markdown(summary))
    print(f"\nStyle report → {out}  (note → {note_path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.voice_eval",
        description="Voice-fidelity blind-A/B eval for the Geo-LLM fine-tune (plan 0008 "
                    "step 26d). Owner-gated: the judge pass makes conductor calls "
                    "(defaults to paid T3), so it refuses to run if the conductor is down.",
    )
    parser.add_argument("--trials", type=Path, default=TRIALS_PATH,
                        help="trial set (default: eval/voice_trials.json)")
    parser.add_argument("--output", type=Path, default=REPORT_PATH,
                        help="report path (default: data/analysis/voice_eval.json)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"blinding seed (default: {DEFAULT_SEED})")
    parser.add_argument("--judge-tier", type=int, default=3,
                        help="conductor tier for the judge (default: 3, paid)")
    parser.add_argument("--style-only", action="store_true",
                        help="compute only the deterministic style metrics (no judge / "
                             "conductor / paid calls); writes a style-only report")
    parser.add_argument("--fingerprint-words", type=int, default=DEFAULT_FINGERPRINT_WORDS,
                        help="how many distinctive corpus words count as the Calhoun "
                             f"fingerprint (default: {DEFAULT_FINGERPRINT_WORDS})")
    args = parser.parse_args(argv)

    if not args.trials.exists():
        print(f"No trial set at {args.trials}. Build one from "
              f"eval/voice_trials.example.json (owner-produced once 26c's adapter exists).")
        return 1

    distinctive = load_distinctive_words(top_n=args.fingerprint_words)

    if args.style_only:
        return _run_style_only(args, distinctive)

    if not require_conductor(
        extra="(Tip: `--style-only` runs the deterministic style metrics offline.)"
    ):
        return 2

    trials = load_trials(args.trials)
    records = evaluate(
        trials,
        judge=_live_judge(args.judge_tier),
        seed=args.seed,
        distinctive_words=distinctive,
        log=lambda m: print(m, flush=True),
    )
    summary = write_report(records, args.output)
    note_path = args.output.with_suffix(".md")
    note_path.write_text(render_markdown(summary) + "\n")
    ft = summary["sources"].get("finetuned", {})
    print(
        f"\nVoice eval ({summary['n_judged']}/{summary['n_trials']} judged): "
        f"finetuned win-rate {ft.get('win_rate', 0):.0%}, "
        f"avg rank {ft.get('avg_rank', 0):.2f}. "
        f"finetuned-over-rag {summary['pairwise'].get('finetuned_over_rag', 0):.0%}.\n"
        f"Report → {args.output}  (note → {note_path})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
