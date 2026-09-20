"""Ask TypeSafe Jev whether each article sounds like a person or like anyone.

Exploratory one-off, deliberately outside the analysis pipeline: load → call → dump.
No retries, no fingerprint-skip, no make-target chain.

    export JEV_API_KEY=...
    .venv/bin/python -m tools.jev_voice_probe --limit 10      # trial first
    .venv/bin/python -m tools.jev_voice_probe                 # whole corpus

Writes ``data/analysis/jev_voice.csv`` (sorted by confidence, clearest calls first)
and ``jev_voice.json`` for the dashboard tab.

Three choices worth knowing about:

* **Bodies are cleaned twice before they are sent**, because both kinds of junk would
  be graded as *his* voice otherwise — the one failure mode that would make this probe
  meaningless. ``strip_wire_boilerplate`` removes Getty photo captions and agency
  credits (22% of passages carry them). Then the corpus-wide repeated paragraphs — his
  standing author bio and footer, **18 of them, 7.3% of all words** — are removed with
  ``training.prepare``'s existing detector. A bio that appears identically in eighty
  articles is boilerplate by definition and would drag every score toward it.
* **The one dateless entry is dropped.** It is the scraped author-listing page, not a
  column.
* **Both questions go in a single call.** Jev evaluates each question in isolation
  against the same state and answers in parallel, so a second question costs latency
  roughly nothing (it does cost input tokens). The Choice gives the split you asked for;
  the Score gives a 1–5 gradient, which is the more useful column if the binary turns out
  to be lopsided.
* **No retry loop**, per the brief. A per-article error is recorded in the row and the
  run continues, because losing 180 good calls to one 429 helps nobody — but an auth
  failure aborts immediately, since every later call would fail the same way.
"""

import argparse
import asyncio
import csv
import json
import os
import sys

from analysis.utils import DATA_DIR, load_articles, strip_wire_boilerplate
from training.prepare import boilerplate_paragraphs
from training.prepare import strip_boilerplate as drop_repeated_paragraphs

CSV_PATH = DATA_DIR / "analysis" / "jev_voice.csv"
JSON_PATH = DATA_DIR / "analysis" / "jev_voice.json"

# Jev bills question + state as input tokens, so the state is bounded. ~6k chars is
# several hundred words past the point where a voice is obvious.
DEFAULT_STATE_CHARS = 6000
# The corpus contains a scraped author-listing page and a few stubs; they are not
# articles and would score as "boilerplate" for uninteresting reasons.
MIN_WORDS = 250

# jevclient is an opt-in extra (`pip install -e .[jev]`), so it is imported inside the
# functions that need it — the repo's convention for optional deps, and what keeps this
# module importable in CI, which installs no extras. tests/test_lint_scope.py imports
# every source module and caught the top-level version of this import.
def build_questions() -> dict:
    from jevclient import Choice, Score

    return {
        "voice": Choice(
            "How would you characterize the writing voice of this article?",
            {
                "unique": "Distinctive, personal style with idiosyncratic phrasing, "
                          "argument structure, or point of view",
                "boilerplate": "Generic, formulaic, could have been written by anyone "
                               "covering this topic",
            },
        ),
        "distinctiveness": Score(
            "How distinctive is this writing as the work of one particular author?",
            [
                "Interchangeable with any competent writer on the subject",
                "Mostly conventional, with occasional personality",
                "Recognizable habits of phrasing and argument",
                "Strongly individual voice",
                "Unmistakable — could not plausibly be anyone else",
            ],
        ),
    }


def clean_body(article: dict, repeated: set[str]) -> str:
    """Wire captions out, then his corpus-wide repeated bio/footer paragraphs out."""
    return drop_repeated_paragraphs(
        strip_wire_boilerplate(article.get("body", "")), repeated
    )


def build_state(article: dict, max_chars: int, repeated: set[str]) -> str:
    """Title, date and a bounded, boilerplate-free excerpt."""
    body = clean_body(article, repeated)
    return (
        f"Title: {article.get('title', '')}\n"
        f"Date: {article.get('date', '')}\n\n"
        f"{body[:max_chars]}"
    )


def eligible(articles: list[dict], min_words: int, repeated: set[str]) -> list[dict]:
    """Real columns only: dated, and long enough once the boilerplate is gone."""
    return [
        a for a in articles
        if a.get("date") and len(clean_body(a, repeated).split()) >= min_words
    ]


async def probe(articles: list[dict], api_key: str, max_chars: int,
                repeated: set[str]) -> list[dict]:
    from jevclient import JevAuthError, JevClient, JevError

    questions = build_questions()
    rows: list[dict] = []
    async with JevClient(api_key) as jev:
        for i, a in enumerate(articles, 1):
            state = build_state(a, max_chars, repeated)
            row = {
                "slug": a.get("slug", ""),
                "title": a.get("title", ""),
                "date": a.get("date", ""),
                "url": a.get("url", ""),
                "words": len(clean_body(a, repeated).split()),
                "snippet": " ".join(state.split())[:300],
            }
            try:
                resp = await jev.ask(state, questions)
            except JevAuthError:
                print("\nJevAuthError — the key was rejected. Aborting; every later "
                      "call would fail the same way.", file=sys.stderr)
                raise
            except JevError as exc:
                row |= {"voice": "", "voice_probability": "", "confidence": "",
                        "distinctiveness": "", "error": f"{type(exc).__name__}: {exc}"}
                rows.append(row)
                print(f"  [{i}/{len(articles)}] {row['slug'][:48]:<48} ERROR {type(exc).__name__}")
                continue

            v = resp.answers["voice"]
            s = resp.answers["distinctiveness"]
            row |= {
                "voice": v.choice,
                "voice_probability": round(v.probabilities.get(v.choice, 0.0), 4),
                "confidence": round(v.confidence, 4),
                "distinctiveness": round(s.score, 3),
                "error": "",
                "_input_tokens": resp.usage.input_tokens,
            }
            rows.append(row)
            print(f"  [{i}/{len(articles)}] {row['slug'][:48]:<48} "
                  f"{v.choice:<11} p={row['voice_probability']:.2f} "
                  f"conf={row['confidence']:.2f} score={row['distinctiveness']:.2f}")
    return rows


def write_outputs(rows: list[dict]) -> None:
    # Clearest calls first — of BOTH kinds, which is the point: the top of the file
    # should be the most obvious "unique" and the most obvious "boilerplate".
    rows.sort(key=lambda r: (r.get("confidence") or 0), reverse=True)
    cols = ["slug", "title", "date", "voice", "voice_probability", "confidence",
            "distinctiveness", "words", "url", "snippet", "error"]
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    scored = [r for r in rows if r.get("voice")]
    counts: dict[str, int] = {}
    for r in scored:
        counts[r["voice"]] = counts.get(r["voice"], 0) + 1
    JSON_PATH.write_text(json.dumps({
        "meta": {
            "n": len(rows),
            "scored": len(scored),
            "errors": sum(1 for r in rows if r.get("error")),
            "counts": counts,
            "mean_distinctiveness": (
                round(sum(r["distinctiveness"] for r in scored) / len(scored), 3)
                if scored else None
            ),
        },
        "articles": [{k: r.get(k) for k in cols} for r in rows],
    }, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None,
                    help="only probe the first N eligible articles (trial runs)")
    ap.add_argument("--state-chars", type=int, default=DEFAULT_STATE_CHARS)
    ap.add_argument("--min-words", type=int, default=MIN_WORDS)
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be sent and the estimated cost; call nothing")
    args = ap.parse_args(argv)

    corpus = load_articles()
    repeated = boilerplate_paragraphs(
        [strip_wire_boilerplate(a.get("body", "")) for a in corpus]
    )
    articles = eligible(corpus, args.min_words, repeated)
    print(f"{len(corpus)} scraped, {len(articles)} eligible "
          f"({len(repeated)} repeated bio/footer paragraphs stripped corpus-wide)")
    if args.limit:
        articles = articles[: args.limit]
    if not articles:
        print("No eligible articles. Has `make scrape` run?")
        return 2

    from jevclient import USD_PER_MILLION_INPUT_TOKENS

    # ~4 chars/token, plus the question text (the package documents ~38 tokens each).
    est_tokens = sum(len(build_state(a, args.state_chars, repeated)) // 4 + 80
                     for a in articles)
    est_cost = est_tokens / 1_000_000 * USD_PER_MILLION_INPUT_TOKENS
    print(f"{len(articles)} articles | ~{est_tokens:,} input tokens | "
          f"~${est_cost:.2f} at ${USD_PER_MILLION_INPUT_TOKENS}/M")

    if args.dry_run:
        print("\n--- state text for the first article ---")
        print(build_state(articles[0], args.state_chars, repeated)[:700])
        print("\n(dry run — nothing sent)")
        return 0

    api_key = os.environ.get("JEV_API_KEY")
    if not api_key:
        print("\nJEV_API_KEY is not set. This repo keeps no keys (see .env.example);\n"
              "export it in your shell:  export JEV_API_KEY=...", file=sys.stderr)
        return 2

    rows = asyncio.run(probe(articles, api_key, args.state_chars, repeated))
    write_outputs(rows)

    used = sum(r.get("_input_tokens", 0) for r in rows)
    print(f"\nwrote {CSV_PATH}\n      {JSON_PATH}")
    print(f"actual input tokens: {used:,} "
          f"(~${used / 1_000_000 * USD_PER_MILLION_INPUT_TOKENS:.2f})")
    print("CSV is sorted by confidence — the clearest calls of both kinds are at the top.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
