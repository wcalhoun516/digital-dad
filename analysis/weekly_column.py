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

from .adjudicate import VALID_VERDICTS

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
