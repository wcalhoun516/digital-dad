"""RAG faithfulness eval harness for "Ask Dad" (plan 0007).

Establishes a re-runnable baseline for whether the dashboard's RAG chat answers
from real corpus passages, cites them correctly, and abstains instead of
hallucinating. This is the bar any future fine-tune (#26) must beat.

Production retrieval lives in ``analysis.semantic_search.search()`` (embed query →
top-k articles by cosine); production generation prompts the conductor to answer
*only* from the retrieved snippets, cite each claim by ``title (year)``, and decline
with "I haven't written about that specifically" when the sources don't cover the
topic. The eval mirrors that exactly.

Following ``analysis.verdict_backfill``, the compute-heavy/networked parts are
isolated behind three injected seams so all scoring logic is unit-testable offline:

- ``retrieve(question, top_k) -> list[source]`` — production retrieval (``search``).
- ``generate(question, sources) -> str`` — the grounded answer (conductor chat).
- ``judge(question, answer, sources) -> dict`` — an LLM-judge (stronger T3 model)
  scoring how many of the answer's claims are grounded in the sources.

Deterministic scorers (abstention detection, retrieved-title citation matching) and
the judge-response parser are pure functions; the CLI (``python -m analysis.rag_eval``
/ ``make rag-eval``) wires the seams to the live conductor and is gated on its
reachability because a live pass makes paid T3 calls.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .utils import DATA_DIR

# Repo-root-relative fixture (source-controlled input, not a generated artifact).
QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
REPORT_PATH = DATA_DIR / "analysis" / "rag_eval.json"

DEFAULT_TOP_K = 8

# Phrases that mark the model declining to answer (production's abstention contract
# plus a couple of natural variants). Matched against the normalized answer.
_ABSTENTION_MARKERS = (
    "haven't written about that",
    "have not written about that",
    "haven't written about this",
    "have not written about this",
    "don't have anything written",
    "no articles about that",
)


# --------------------------------------------------------------------------- #
# Text normalization + deterministic scorers (pure)
# --------------------------------------------------------------------------- #

def normalize(text: str) -> str:
    """Lowercase, fold typographic punctuation to spaces, collapse whitespace.

    Corpus titles use curly quotes and en/em dashes; normalizing both the answer
    and the candidate title through this makes substring matching robust to them.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    # Drop apostrophes/quotes so "Europe's" matches a model's "Europes"; everything
    # else non-alphanumeric becomes a space (dashes, slashes, punctuation are gaps).
    text = re.sub(r"['‘’ʼ`\"“”]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_abstention(answer: str) -> bool:
    """True if *answer* declines to answer (or is empty)."""
    norm = normalize(answer)
    if not norm:
        return True
    return any(marker in norm for marker in (normalize(m) for m in _ABSTENTION_MARKERS))


def cited_retrieved_titles(
    answer: str, retrieved: list[dict]
) -> tuple[list[str], list[str]]:
    """Split retrieved titles into (mentioned in answer, not mentioned).

    A retrieved title counts as cited when its normalized form is a substring of the
    normalized answer. Returns the original (un-normalized) titles, preserving the
    order they appear in ``retrieved``.
    """
    norm_answer = normalize(answer)
    present: list[str] = []
    absent: list[str] = []
    for src in retrieved:
        title = src.get("title") or ""
        norm_title = normalize(title)
        if norm_title and norm_title in norm_answer:
            present.append(title)
        else:
            absent.append(title)
    return present, absent


def parse_judgment(text: str) -> dict | None:
    """Extract the judge's ``{claims_total, claims_grounded, citations_valid,
    abstained}`` object from a model reply.

    Tolerates prose and markdown fences around the JSON (like
    ``verdict_backfill.parse_verdict``). Returns ``None`` if no JSON object can be
    found. Missing fields default safely and ``claims_grounded`` is clamped to
    ``claims_total`` so a confused judge can't push the grounding rate above 1.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, AttributeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    total = _as_int(obj.get("claims_total"), 0)
    grounded = _as_int(obj.get("claims_grounded"), 0)
    grounded = max(0, min(grounded, total))
    return {
        "claims_total": total,
        "claims_grounded": grounded,
        "citations_valid": bool(obj.get("citations_valid", False)),
        "abstained": bool(obj.get("abstained", False)),
    }


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Harness (injected seams)
# --------------------------------------------------------------------------- #

def evaluate(
    questions: list[dict],
    retrieve: Callable[..., list[dict]],
    generate: Callable[[str, list[dict]], str],
    judge: Callable[[str, str, list[dict]], dict | None],
    *,
    top_k: int = DEFAULT_TOP_K,
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Run retrieval + generation + judging for each question; return per-question rows.

    ``retrieve``/``generate``/``judge`` are injected so the loop is testable offline.
    A judge that returns ``None`` (unparseable) is recorded with zeroed claim counts
    rather than aborting the run.
    """
    records: list[dict] = []
    for i, q in enumerate(questions, 1):
        question = q.get("question", "")
        answerable = bool(q.get("answerable", True))
        sources = retrieve(question, top_k=top_k)
        answer = generate(question, sources)
        abstained = is_abstention(answer)
        present, absent = cited_retrieved_titles(answer, sources)

        judgment = judge(question, answer, sources) or {}
        claims_total = _as_int(judgment.get("claims_total"), 0)
        claims_grounded = _as_int(judgment.get("claims_grounded"), 0)

        abstention_correct = (abstained == (not answerable)) if not answerable else None

        records.append(
            {
                "id": q.get("id"),
                "question": question,
                "answerable": answerable,
                "answer": answer,
                "num_retrieved": len(sources),
                "retrieved_titles": [s.get("title") for s in sources],
                "cited_present": present,
                "cited_absent": absent,
                "abstained": abstained,
                "abstention_correct": abstention_correct,
                "claims_total": claims_total,
                "claims_grounded": claims_grounded,
                "citations_valid": bool(judgment.get("citations_valid", False)),
            }
        )
        log(f"  [{i}/{len(questions)}] {q.get('id')}: "
            f"{'abstained' if abstained else 'answered'}, "
            f"{claims_grounded}/{claims_total} grounded")
    return records


def aggregate(records: list[dict]) -> dict:
    """Compute headline faithfulness metrics from per-question rows.

    - ``grounding_rate`` = grounded claims / total claims, over answerable questions
      (the trust number: how much of what it asserts is backed by a retrieved passage).
    - ``hallucination_rate`` = 1 - grounding_rate.
    - ``abstention_accuracy`` = fraction of *unanswerable* questions it declined on.
    - ``citation_coverage`` = answerable answers that name at least one retrieved title.
    """
    n = len(records)
    answerable = [r for r in records if r.get("answerable")]
    unanswerable = [r for r in records if not r.get("answerable")]

    total_claims = sum(r.get("claims_total", 0) for r in answerable)
    grounded_claims = sum(r.get("claims_grounded", 0) for r in answerable)
    grounding_rate = (grounded_claims / total_claims) if total_claims else 0.0

    abstained_correct = sum(1 for r in unanswerable if r.get("abstained"))
    abstention_accuracy = (
        abstained_correct / len(unanswerable) if unanswerable else 0.0
    )

    cited_any = sum(1 for r in answerable if r.get("cited_present"))
    citation_coverage = (cited_any / len(answerable)) if answerable else 0.0

    # Over-refusal: abstaining on a question the corpus *can* answer (a retrieval or
    # grounding failure that looks safe but hides a real miss).
    false_abstain = sum(1 for r in answerable if r.get("abstained"))
    false_abstention_rate = (false_abstain / len(answerable)) if answerable else 0.0

    return {
        "n_questions": n,
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "total_claims": total_claims,
        "grounded_claims": grounded_claims,
        "grounding_rate": round(grounding_rate, 4),
        "hallucination_rate": round(1.0 - grounding_rate, 4),
        "abstention_accuracy": round(abstention_accuracy, 4),
        "false_abstention_rate": round(false_abstention_rate, 4),
        "citation_coverage": round(citation_coverage, 4),
    }


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


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    """Load the held-out question set fixture."""
    data = json.loads(Path(path).read_text())
    return data.get("questions", [])


# --------------------------------------------------------------------------- #
# Live seams (conductor) + CLI — owner-gated; makes paid T3 calls
# --------------------------------------------------------------------------- #

# Mirrors the dashboard's Ask Dad system prompt closely enough that the eval
# measures production behavior, not a different prompt.
_GEN_SYSTEM = (
    "You ARE Dr. George Calhoun — Forbes columnist, economist, and relentless "
    "contrarian, speaking in the first person.\n"
    "RULES:\n"
    "- Answer ONLY from the source articles provided below. These are things you "
    "actually wrote.\n"
    "- Cite each claim with the article title and year in parentheses.\n"
    "- If the sources don't cover the topic, say \"I haven't written about that "
    "specifically\" — don't fabricate.\n"
    "- Be specific and opinionated; use data points from the articles.\n\n"
    "--- YOUR PUBLISHED ARTICLES (source of truth) ---\n\n"
)

_JUDGE_PROMPT = """You are auditing whether an answer is faithful to its source passages.

Given a QUESTION, an ANSWER, and the SOURCE passages the answer was supposed to use, count the answer's factual claims and how many are supported by at least one source.

Return ONLY a JSON object (no markdown, no commentary):
{{
  "claims_total": <int: number of distinct factual claims the answer makes>,
  "claims_grounded": <int: how many of those are supported by some SOURCE passage>,
  "citations_valid": <true if every article the answer cites appears in SOURCES, else false>,
  "abstained": <true if the answer declines to answer / says it hasn't covered the topic>
}}

QUESTION
{question}

ANSWER
{answer}

SOURCES
{sources}"""


def _format_sources(sources: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        title = s.get("title") or "Untitled"
        year = (s.get("date") or "")[:4]
        snippet = (s.get("snippet") or "").strip()
        blocks.append(f"[{i}] \"{title}\" ({year})\n{snippet}".strip())
    return "\n\n".join(blocks) if blocks else "(no sources retrieved)"


def _live_retrieve(top_k: int = DEFAULT_TOP_K) -> Callable[..., list[dict]]:
    """Retrieval seam backed by production semantic search, enriched with snippets."""
    from . import semantic_search

    # The dashboard export carries the article snippets the generator needs.
    export = json.loads(semantic_search.DASHBOARD_EXPORT_PATH.read_text())
    snippet_by_slug = dict(zip(export.get("slugs", []), export.get("snippets", [])))

    def retrieve(question: str, top_k: int = top_k) -> list[dict]:
        results = semantic_search.search(question, top_k=top_k)
        for r in results:
            r["snippet"] = snippet_by_slug.get(r.get("slug"), "")
        return results

    return retrieve


def _live_generate(tier: int = 2) -> Callable[[str, list[dict]], str]:
    from .predictions import _call, _get_client

    client = _get_client()

    def generate(question: str, sources: list[dict]) -> str:
        prompt = _GEN_SYSTEM + _format_sources(sources) + f"\n\nQUESTION: {question}"
        return _call(client, prompt, max_tokens=600, tier=tier)

    return generate


def _live_judge(tier: int = 3) -> Callable[[str, str, list[dict]], dict | None]:
    from .predictions import _call, _get_client

    client = _get_client()

    def judge(question: str, answer: str, sources: list[dict]) -> dict | None:
        prompt = _JUDGE_PROMPT.format(
            question=question, answer=answer, sources=_format_sources(sources)
        )
        return parse_judgment(_call(client, prompt, max_tokens=400, tier=tier))

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
        prog="python -m analysis.rag_eval",
        description="RAG faithfulness eval for Ask Dad. Owner-gated: the generation "
                    "and judge passes make conductor calls (judge defaults to paid "
                    "T3), so it refuses to run if the conductor is down.",
    )
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH,
                        help="question-set fixture (default: eval/questions.json)")
    parser.add_argument("--output", type=Path, default=REPORT_PATH,
                        help="report path (default: data/analysis/rag_eval.json)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help="retrieved articles per question (default: 8)")
    parser.add_argument("--limit", type=int, default=None,
                        help="evaluate at most N questions this run")
    parser.add_argument("--gen-tier", type=int, default=2,
                        help="conductor tier for generation (default: 2, free local)")
    parser.add_argument("--judge-tier", type=int, default=3,
                        help="conductor tier for the judge (default: 3, paid)")
    args = parser.parse_args(argv)

    if not args.questions.exists():
        print(f"No question set at {args.questions}.")
        return 1
    if not _conductor_up():
        print("Conductor is unreachable at http://127.0.0.1:8080 — start it before "
              "running the eval (the judge pass makes paid T3 calls). Aborting.")
        return 2

    questions = load_questions(args.questions)
    if args.limit is not None:
        questions = questions[: args.limit]

    records = evaluate(
        questions,
        retrieve=_live_retrieve(args.top_k),
        generate=_live_generate(args.gen_tier),
        judge=_live_judge(args.judge_tier),
        top_k=args.top_k,
        log=lambda m: print(m, flush=True),
    )
    summary = write_report(records, args.output)
    print(
        f"\nRAG eval baseline ({summary['n_questions']} questions): "
        f"grounding {summary['grounding_rate']:.0%}, "
        f"hallucination {summary['hallucination_rate']:.0%}, "
        f"abstention {summary['abstention_accuracy']:.0%} on "
        f"{summary['n_unanswerable']} unanswerable, "
        f"citation coverage {summary['citation_coverage']:.0%}.\n"
        f"Report → {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
