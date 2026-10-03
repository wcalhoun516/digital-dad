"""Tests for analysis/weekly_column.py — the weekly column's compose/render core (roadmap #45).

Pure logic only. Retrieval and generation are injected seams, faked here, so no conductor,
no network and no corpus are touched. Synthetic content throughout — no real family text.
"""

import pytest

from analysis.weekly_column import build_evidence_pack


def _claim(slug, date, verdict="vindicated", claim=None, title=None):
    return {
        "claim": claim or f"claim from {slug}",
        "date": date,
        "slug": slug,
        "title": title or f"Title {slug}",
        "url": f"https://example.com/{slug}",
        "confidence_language": "confident",
        "verdict": verdict,
        "verdict_source": "llm",
    }


def _position(claims, subject="widget policy"):
    return {
        "id": "pos:widget-policy",
        "subject": subject,
        "aliases": [subject],
        "claims": claims,
        "span": [min(c["date"] for c in claims), max(c["date"] for c in claims)]
        if claims
        else [None, None],
        "record": {"vindicated": 1, "wrong": 1, "mixed": 0, "unfalsifiable": 0, "pending": 0},
    }


def _hit(slug, date="2021-01-01", snippet=None):
    return {
        "slug": slug,
        "title": f"Title {slug}",
        "date": date,
        "url": f"https://example.com/{slug}",
        "snippet": f"passage from {slug}" if snippet is None else snippet,
    }


def _retrieve(hits):
    calls = []

    def retrieve(query, top_k):
        calls.append((query, top_k))
        return [dict(h) for h in hits][:top_k]

    retrieve.calls = calls
    return retrieve


class TestBuildEvidencePack:
    def test_claims_from_one_article_share_one_number(self):
        # A footnote is an article. Two claims from the same piece are one source, so the
        # citation gate checks a quote against the article it actually came from.
        position = _position([_claim("a", "2020-01-01"), _claim("a", "2020-01-01", "wrong")])
        pack = build_evidence_pack(position, retrieve=_retrieve([]))
        assert [s["n"] for s in pack["sources"]] == [1]
        assert len(pack["sources"][0]["claims"]) == 2

    def test_sources_numbered_from_one_in_date_order(self):
        position = _position([_claim("late", "2024-05-01"), _claim("early", "2019-02-01")])
        pack = build_evidence_pack(position, retrieve=_retrieve([]))
        assert [(s["n"], s["slug"]) for s in pack["sources"]] == [(1, "early"), (2, "late")]

    def test_each_source_is_bound_to_slug_title_and_url(self):
        position = _position([_claim("a", "2020-01-01", title="On Widgets")])
        (source,) = build_evidence_pack(position, retrieve=_retrieve([]))["sources"]
        assert source["slug"] == "a"
        assert source["title"] == "On Widgets"
        assert source["url"] == "https://example.com/a"
        assert source["date"] == "2020-01-01"

    def test_retrieved_passage_attaches_to_an_existing_claim_source(self):
        position = _position([_claim("a", "2020-01-01")])
        pack = build_evidence_pack(position, retrieve=_retrieve([_hit("a")]))
        assert len(pack["sources"]) == 1
        assert pack["sources"][0]["passage"] == "passage from a"

    def test_retrieved_article_without_claims_becomes_its_own_source(self):
        position = _position([_claim("a", "2020-01-01")])
        pack = build_evidence_pack(position, retrieve=_retrieve([_hit("b", "2022-03-03")]))
        b = next(s for s in pack["sources"] if s["slug"] == "b")
        assert b["claims"] == []
        assert b["passage"] == "passage from b"

    def test_retrieved_article_with_no_text_is_not_a_source(self):
        # A source the composer cannot read is a citation it can only invent around.
        position = _position([_claim("a", "2020-01-01")])
        pack = build_evidence_pack(position, retrieve=_retrieve([_hit("b", snippet="  ")]))
        assert [s["slug"] for s in pack["sources"]] == ["a"]

    def test_passage_only_sources_are_capped(self):
        position = _position([_claim("a", "2020-01-01")])
        hits = [_hit(f"p{i}", f"2021-01-0{i + 1}") for i in range(6)]
        pack = build_evidence_pack(position, retrieve=_retrieve(hits), max_passages=2)
        assert [s["slug"] for s in pack["sources"] if not s["claims"]] == ["p0", "p1"]

    def test_overlapping_hits_do_not_eat_the_passage_budget(self):
        # top_k leaves room for the claim articles retrieval will also return.
        position = _position([_claim("a", "2020-01-01"), _claim("b", "2020-02-01")])
        retrieve = _retrieve([_hit("a"), _hit("b"), _hit("c"), _hit("d")])
        pack = build_evidence_pack(position, retrieve=retrieve, max_passages=2)
        assert retrieve.calls[0][1] == 4
        assert {s["slug"] for s in pack["sources"]} == {"a", "b", "c", "d"}

    def test_query_defaults_to_the_subject(self):
        retrieve = _retrieve([])
        build_evidence_pack(_position([_claim("a", "2020-01-01")]), retrieve=retrieve)
        assert retrieve.calls[0][0] == "widget policy"

    def test_query_can_be_this_weeks_headline(self):
        retrieve = _retrieve([])
        pack = build_evidence_pack(
            _position([_claim("a", "2020-01-01")]), retrieve=retrieve, query="Widgets surge"
        )
        assert retrieve.calls[0][0] == "Widgets surge"
        assert pack["query"] == "Widgets surge"

    def test_adjudicated_claims_are_chosen_before_unjudged_ones(self):
        claims = [
            _claim("p", "2025-01-01", "pending"),
            _claim("u", "2025-01-02", "unfalsifiable"),
            _claim("w", "2019-01-01", "wrong"),
        ]
        pack = build_evidence_pack(_position(claims), retrieve=_retrieve([]), max_claims=1)
        assert [s["slug"] for s in pack["sources"]] == ["w"]

    def test_most_recent_adjudicated_claims_are_chosen_first(self):
        claims = [_claim(f"c{y}", f"{y}-01-01") for y in (2019, 2023, 2021)]
        pack = build_evidence_pack(_position(claims), retrieve=_retrieve([]), max_claims=2)
        assert [s["slug"] for s in pack["sources"]] == ["c2021", "c2023"]

    def test_record_and_span_are_the_whole_subjects_not_the_selection(self):
        # The closing record is his record on the subject; trimming the claims shown to the
        # composer must not quietly trim the scoreboard too.
        claims = [_claim(f"c{y}", f"{y}-01-01") for y in (2019, 2023, 2021)]
        position = _position(claims)
        pack = build_evidence_pack(position, retrieve=_retrieve([]), max_claims=1)
        assert pack["record"] == position["record"]
        assert pack["span"] == ["2019-01-01", "2023-01-01"]
        assert pack["subject"] == "widget policy"
        assert pack["position_id"] == "pos:widget-policy"

    def test_claim_entries_carry_text_date_and_verdict(self):
        position = _position([_claim("a", "2020-01-01", "mixed", claim="Widgets will rise.")])
        (source,) = build_evidence_pack(position, retrieve=_retrieve([]))["sources"]
        assert source["claims"] == [
            {"claim": "Widgets will rise.", "date": "2020-01-01", "verdict": "mixed"}
        ]

    def test_pack_does_not_mutate_the_position(self):
        position = _position([_claim("a", "2020-01-01")])
        before = repr(position)
        build_evidence_pack(position, retrieve=_retrieve([_hit("a")]))
        assert repr(position) == before

    def test_position_with_no_claims_is_refused(self):
        # No claims means no position: there is nothing he held, so nothing to write about.
        with pytest.raises(ValueError):
            build_evidence_pack(_position([]), retrieve=_retrieve([_hit("a")]))
