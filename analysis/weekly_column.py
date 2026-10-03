"""The weekly column — evidence pack, composition and rendering (roadmap #45, first slice).

The weekly commentary the owner actually wants: this week's news, in his voice, every claim
citable to a real article, closing with his adjudicated record on the subject. Design: the
approved 2026-09-07 spec, Arc B (`docs/superpowers/specs/2026-09-07-next-phase-design.md`).

This module is the part of that pipeline that only #45 owns::

    position ─► build_evidence_pack ─► compose ─► [verify — #46] ─► render_html
                     (retrieve)        (generate)

Subject *selection* (#44) picks the position; the positions index (#43) supplies it; the
citation gate (#46) sits between ``compose`` and ``render_html``. **None of them is wired here,
and there is deliberately no CLI or runner yet**: the spec's rule is that an unverified column
is never rendered or drafted, and until the gate exists there is nothing to enforce that with.

Three choices worth knowing:

**One source number per article.** His claims and the retrieved passages fold into sources
keyed by slug, numbered ``[1..n]`` in date order. A footnote is an article, and the gate checks
a quoted span against the article it cites — two numbers for one piece would let a quote pass
against the wrong one.

**The record is rendered, never generated.** The closing "his record on the subject" block is
built from the position's own tally in ``render_html``. The composer is told the record exists
and is *not* asked to state it, so a model cannot round 2-of-5 up to "usually right". The tally
is the whole subject's, not just the claims chosen for the pack.

**``render_html`` fails closed on its own.** A marker with no source raises instead of
rendering a dead footnote. That duplicates one line of the gate on purpose: if a later runner
is ever wired without ``verify``, a fabricated citation still cannot reach the family.

Retrieval and generation are injected seams (``retrieve``, ``generate``), mirroring
``rag_eval.py``, so all of it is tested offline. The author's name is a parameter, not a
constant, so the same core can write for anyone the archive is about.
"""

import re

from .adjudicate import VALID_VERDICTS

# The archive's subject. A parameter everywhere it matters; this is only the default.
DEFAULT_AUTHOR = "Dr. George Calhoun"

# The verdicts that mean the archive actually ruled on a call. A column leans on the claims
# that were tested before the ones that were never testable or not yet judged.
_ADJUDICATED = ("vindicated", "mixed", "wrong")

DEFAULT_MAX_CLAIMS = 6
DEFAULT_MAX_PASSAGES = 4


def _select_claims(claims: list[dict], max_claims: int) -> list[dict]:
    """Adjudicated claims first, most recent first within each group."""
    ranked = sorted(claims, key=lambda c: (c.get("date") or "", c.get("slug", "")), reverse=True)
    ranked.sort(key=lambda c: c.get("verdict") not in _ADJUDICATED)  # stable: keeps recency
    return ranked[:max_claims]


def _new_source(item: dict, date: str) -> dict:
    return {
        "slug": item.get("slug", ""),
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "date": date or "",
        "claims": [],
        "passage": "",
    }


def build_evidence_pack(
    position: dict,
    *,
    retrieve,
    query: str | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    max_passages: int = DEFAULT_MAX_PASSAGES,
) -> dict:
    """His claims on a subject plus supporting passages, numbered ``[1..n]`` per article.

    ``retrieve(query, top_k)`` returns ranked articles carrying ``slug``/``title``/``url``/
    ``date``/``snippet`` (``rag_eval._live_retrieve`` is the live shape). ``query`` defaults
    to the subject; a runner passes this week's headline so the passages fit the news.
    """
    claims = position.get("claims") or []
    if not claims:
        raise ValueError(f"position {position.get('id')!r} has no claims to write from")

    by_slug: dict[str, dict] = {}
    for c in _select_claims(claims, max_claims):
        source = by_slug.setdefault(c["slug"], _new_source(c, c.get("date", "")))
        source["claims"].append(
            {"claim": c.get("claim", ""), "date": c.get("date", ""), "verdict": c.get("verdict")}
        )

    query = query or position["subject"]
    # Retrieval will often return the claim articles too; leave room so they cannot crowd
    # out the new passages the budget is for.
    hits = retrieve(query, max_passages + len(by_slug))
    added = 0
    for hit in hits:
        text = (hit.get("snippet") or "").strip()
        if not text:
            continue
        slug = hit.get("slug", "")
        if slug in by_slug:
            by_slug[slug]["passage"] = by_slug[slug]["passage"] or text
        elif added < max_passages:
            by_slug[slug] = _new_source(hit, hit.get("date", ""))
            by_slug[slug]["passage"] = text
            added += 1

    sources = sorted(by_slug.values(), key=lambda s: (s["date"], s["slug"]))
    for n, source in enumerate(sources, 1):
        source["n"] = n

    return {
        "position_id": position.get("id"),
        "subject": position["subject"],
        "query": query,
        "span": list(position.get("span") or [None, None]),
        "record": {v: (position.get("record") or {}).get(v, 0) for v in VALID_VERDICTS},
        "sources": sources,
    }



# --------------------------------------------------------------------------- #
# Composition — the in-voice column with [n] markers
# --------------------------------------------------------------------------- #

_PROMPT = """You are {author}, writing this week's column in your own voice — the voice of the \
sources below, which are things you actually wrote.

SUBJECT: {subject}
{news}
RULES
- Write 4 to 6 paragraphs, separated by a blank line. Put a title on the first line as \
"Title: ...".
- Every paragraph must cite at least one source with its number in square brackets, like [2].
- Cite only the numbers listed below. Never invent a source.
- Anything you put in quotation marks must be copied exactly, word for word, from a passage \
below. Paraphrase freely, but never misquote.
- Where a source says a claim went wrong, do not present it as having come good.
- Do not state your overall track record or a score on this subject; that record is appended \
to the column separately, from the archive's own tally.
{feedback}
SOURCES
{sources}"""

_FEEDBACK = """
YOUR PREVIOUS DRAFT WAS REJECTED. Fix every one of these and write the column again:
{errors}
"""


def _format_source(source: dict) -> str:
    lines = [f'[{source["n"]}] "{source["title"] or "Untitled"}" ({source["date"] or "undated"})']
    for c in source["claims"]:
        lines.append(f"  You claimed ({c['date']}): {c['claim']}  [the archive judges this: {c['verdict']}]")
    if source["passage"]:
        lines.append(f"  Passage: {source['passage']}")
    return "\n".join(lines)


def build_prompt(pack: dict, *, author: str = DEFAULT_AUTHOR, feedback=()) -> str:
    """The grounded composition prompt. ``feedback`` is the gate's errors from a failed draft."""
    query = pack.get("query")
    news = f"THIS WEEK'S NEWS: {query}\n" if query and query != pack["subject"] else ""
    errors = "\n".join(f"- {e}" for e in feedback)
    return _PROMPT.format(
        author=author,
        subject=pack["subject"],
        news=news,
        feedback=_FEEDBACK.format(errors=errors) if feedback else "",
        sources="\n\n".join(_format_source(s) for s in pack["sources"]),
    )


_TITLE = re.compile(r"^\s*(?:#+\s*|title:\s*)(?P<title>.+?)\s*$", re.IGNORECASE)
_GROUPED_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)+)\]")
_MARKER = re.compile(r"\[(\d+)\]")


def _split_grouped(match: re.Match) -> str:
    return "".join(f"[{n.strip()}]" for n in match.group(1).split(","))


def parse_column(text: str) -> dict:
    """Split model output into a title, paragraphs and the source numbers it cites.

    Grouped markers (``[1, 3]``) are rewritten as ``[1][3]`` so everything downstream sees
    one form. Text is otherwise kept exactly as written — the em-dashes are half the voice.
    """
    lines = [ln for ln in (text or "").splitlines() if not ln.strip().startswith("```")]
    title = None
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is not None and (m := _TITLE.match(lines[first])):
        title = m.group("title")
        del lines[first]

    paragraphs, current = [], []
    for line in lines + [""]:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(_GROUPED_MARKER.sub(_split_grouped, " ".join(current)))
            current = []

    markers = sorted({int(n) for p in paragraphs for n in _MARKER.findall(p)})
    return {"title": title, "paragraphs": paragraphs, "markers": markers}


def compose(pack: dict, *, generate, author: str = DEFAULT_AUTHOR, feedback=()) -> dict:
    """Write the column. ``generate(prompt, sources) -> str`` is the conductor at T2 live.

    The pack's sources go to ``generate`` beside the prompt so the live seam can declare
    their provenance (``assert_remote_allowed``) without re-deriving it from text.
    """
    raw = generate(build_prompt(pack, author=author, feedback=feedback), pack["sources"])
    return {**parse_column(raw), "raw": raw}
