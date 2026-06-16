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

Deferred to a future slice (kept out of this PR to avoid depending on the unmerged 26c
module): folding ``training.finetune_config.style_metrics`` into each record as a cheap
deterministic companion to the judge's voice ranking.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Hashable

from .utils import DATA_DIR

# Repo-root-relative fixture template (the real trials are owner-produced once the 26c
# adapter exists and are not committed — see eval/voice_trials.example.json).
TRIALS_PATH = Path(__file__).resolve().parent.parent / "eval" / "voice_trials.json"
REPORT_PATH = DATA_DIR / "analysis" / "voice_eval.json"

DEFAULT_SEED = 1337


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
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Blind-rank each trial's candidates via *judge*; return per-trial rows.

    Each trial blinds its candidates with a per-trial seed derived from *seed* and the
    trial id, so the A/B/C assignment varies between trials but stays reproducible. A
    judge that returns ``None`` (unparseable) yields an empty ranking rather than
    aborting the run.
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
        records.append(
            {
                "id": trial.get("id"),
                "prompt": prompt,
                "sources": sorted(candidates),
                "blinding": mapping,
                "ranking": ranking,
                "winner": ranking[0] if ranking else None,
            }
        )
        log(f"  [{i}/{len(trials)}] {trial.get('id')}: "
            f"{'/'.join(ranking) if ranking else 'unjudged'}")
    return records


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

    return {
        "n_trials": len(records),
        "n_judged": len(judged),
        "sources": per_source,
        "pairwise": pairwise,
    }


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


def _conductor_up(url: str = "http://127.0.0.1:8080/v1") -> bool:
    import urllib.error
    from urllib.request import urlopen

    try:
        with urlopen(url.rstrip("/") + "/models", timeout=4) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


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
    args = parser.parse_args(argv)

    if not args.trials.exists():
        print(f"No trial set at {args.trials}. Build one from "
              f"eval/voice_trials.example.json (owner-produced once 26c's adapter exists).")
        return 1
    if not _conductor_up():
        print("Conductor is unreachable at http://127.0.0.1:8080 — start it before "
              "running the eval (the judge pass makes paid T3 calls). Aborting.")
        return 2

    trials = load_trials(args.trials)
    records = evaluate(
        trials,
        judge=_live_judge(args.judge_tier),
        seed=args.seed,
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
