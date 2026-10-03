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

import html
import re

from .adjudicate import VALID_VERDICTS
from .year_in_review import _TALLY_PHRASE, _VERDICT_COLOR, ADJUDICATED_VERDICTS, _join_clauses

# The archive's subject. A parameter everywhere it matters; this is only the default.
DEFAULT_AUTHOR = "Dr. George Calhoun"


DEFAULT_MAX_CLAIMS = 6
DEFAULT_MAX_PASSAGES = 4


def _select_claims(claims: list[dict], max_claims: int) -> list[dict]:
    """Adjudicated claims first, most recent first within each group."""
    ranked = sorted(claims, key=lambda c: (c.get("date") or "", c.get("slug", "")), reverse=True)
    ranked.sort(key=lambda c: c.get("verdict") not in ADJUDICATED_VERDICTS)  # stable: keeps recency
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



# --------------------------------------------------------------------------- #
# Rendering — the email body, with the record rendered from the tally
# --------------------------------------------------------------------------- #

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #2a2a2a; line-height: 1.7;">
  <div style="border-bottom: 2px solid #c9a84c; padding-bottom: 12px; margin-bottom: 24px;">
    <h1 style="font-size: 1.4em; font-weight: 400; margin: 0;">{title}</h1>
    <p style="font-size: 0.85em; color: #888; margin: 4px 0 0;">{subtitle}</p>
  </div>

{paragraphs}

  <div style="border-left: 3px solid #c9a84c; padding: 12px 20px; margin: 28px 0; font-size: 0.95em; color: #333;">
    <p style="font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.05em; color: #888; margin: 0 0 6px;">The record on {subject}</p>
    <p style="margin: 0;">{record}</p>
  </div>

  <h2 style="font-size: 1.1em; font-weight: 400; margin: 24px 0 8px;">Sources</h2>
  <ol style="padding-left: 20px; margin: 0; font-size: 0.85em; color: #555;">
{sources}
  </ol>

  <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 0.8em; color: #aaa; text-align: center;">
    Digital Dad &middot; The Intellectual Archive of {author}
  </div>
</body>
</html>
"""

_PARAGRAPH = '  <p style="font-size: 1.02em; margin: 0 0 16px;">{text}</p>'
_MARKER_LINK = '<a href="{url}" style="color: #c9a84c; text-decoration: none;">[{n}]</a>'
_SOURCE_ITEM = (
    '    <li value="{n}" style="margin-bottom: 4px;">'
    '<a href="{url}" style="color: #c9a84c; text-decoration: none;">{title}</a> ({date})</li>'
)
_RECORD_TALLY = '<strong style="color: {color};">{phrase}</strong>'


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _years(span) -> str:
    years = sorted({d[:4] for d in (span or []) if d})
    if not years:
        return ""
    return years[0] if years[0] == years[-1] else f"{years[0]}\u2013{years[-1]}"


def record_sentence(record: dict, subject: str, span) -> str:
    """One honest line about the subject's adjudicated record, as plain text."""
    ruled = sum(record.get(v, 0) for v in ADJUDICATED_VERDICTS)
    unruled = sum(record.get(v, 0) for v in VALID_VERDICTS) - ruled
    if not ruled:
        noun = "call" if unruled == 1 else "calls"
        return f"None of the {unruled} {noun} on {subject} has been ruled on yet."
    years = _years(span)
    clauses = [_TALLY_PHRASE[v].format(n=record[v]) for v in ADJUDICATED_VERDICTS if record.get(v)]
    sentence = (
        f"Of the {ruled} {'call' if ruled == 1 else 'calls'} on {subject} the archive has ruled "
        f"on{f' ({years})' if years else ''}, {_join_clauses(clauses)}."
    )
    if unruled:
        sentence += f" {unruled} more were never testable or are not yet judged."
    return sentence


def _record_html(record: dict, subject: str, span) -> str:
    # Escape the plain sentence, then colour each tally phrase — the words stay the same ones
    # record_sentence() states, so the text and the email cannot disagree.
    out = _esc(record_sentence(record, subject, span))
    for v in ADJUDICATED_VERDICTS:
        if record.get(v):
            phrase = _esc(_TALLY_PHRASE[v].format(n=record[v]))
            out = out.replace(phrase, _RECORD_TALLY.format(color=_VERDICT_COLOR[v], phrase=phrase), 1)
    return out


def render_html(
    column: dict, pack: dict, *, author: str = DEFAULT_AUTHOR, week_of: str | None = None
) -> str:
    """Render a composed column as a Georgia-serif email body. All model text is escaped.

    Raises ``ValueError`` on an empty column or a marker with no source in the pack.
    """
    paragraphs = column.get("paragraphs") or []
    if not paragraphs:
        raise ValueError("the column has no paragraphs to render")
    by_n = {s["n"]: s for s in pack["sources"]}
    unresolved = sorted({int(n) for p in paragraphs for n in _MARKER.findall(p)} - set(by_n))
    if unresolved:
        cited = ", ".join(f"[{n}]" for n in unresolved)
        raise ValueError(f"cites {cited}, which the evidence pack does not contain")

    def link(match: re.Match) -> str:
        n = int(match.group(1))
        return _MARKER_LINK.format(url=html.escape(by_n[n]["url"] or "#", quote=True), n=n)

    body = "\n".join(_PARAGRAPH.format(text=_MARKER.sub(link, _esc(p))) for p in paragraphs)
    cited = sorted({int(n) for p in paragraphs for n in _MARKER.findall(p)})
    sources = "\n".join(
        _SOURCE_ITEM.format(
            n=n,
            url=html.escape(by_n[n]["url"] or "#", quote=True),
            title=_esc(by_n[n]["title"] or "Untitled"),
            date=_esc(by_n[n]["date"] or "undated"),
        )
        for n in cited
    )
    return _HTML_TEMPLATE.format(
        title=_esc(column.get("title") or pack["subject"]),
        subtitle=_esc(f"Week of {week_of}" if week_of else "The weekly column"),
        paragraphs=body,
        subject=_esc(pack["subject"]),
        record=_record_html(pack["record"], pack["subject"], pack["span"]),
        sources=sources,
        author=_esc(author),
    )
