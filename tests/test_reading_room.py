"""Tests for analysis.reading_room — the family full-article reader (roadmap #21).

Pure/offline: the builder takes an in-memory ``themes.json``-shaped article list plus an
injectable ``load_body`` callable, so these tests make no conductor calls and touch no disk
(no real ``data/raw`` files needed).
"""

import pytest

from analysis import reading_room as rr


@pytest.fixture
def articles() -> list[dict]:
    """Four theme-tagged articles (one undated author-listing page that must be dropped)."""
    return [
        {
            "slug": "george-calhoun",
            "title": "George Calhoun",
            "date": "",
            "url": "https://www.forbes.com/sites/georgecalhoun/archive/",
            "word_count": 267,
            "cluster_label": "Huawei / Technology / Wireless",
        },
        {
            "slug": "bitcoin-is-a-signal",
            "title": "Bitcoin Is A Signal",
            "date": "2021-05-10",
            "url": "https://www.forbes.com/b1/",
            "word_count": 1200,
            "cluster_label": "Crypto / Bitcoin / Blockchain",
        },
        {
            "slug": "the-fed-is-late",
            "title": "The Fed Is Late",
            "date": "2020-07-12",
            "url": "https://www.forbes.com/f1/",
            "word_count": 800,
            "cluster_label": "Fed / Inflation / Rates",
        },
        {
            "slug": "inflation-returns",
            "title": "Inflation Returns",
            "date": "2022-01-03",
            "url": "https://www.forbes.com/i1/",
            "word_count": 2000,
            "cluster_label": "Fed / Inflation / Rates",
        },
    ]


BODIES = {
    "bitcoin-is-a-signal": "First para about bitcoin.\n\nSecond para.\n\n  \n\nThird para.",
    "the-fed-is-late": "The Fed moved too slowly.",
    "inflation-returns": "Prices are climbing again.",
}


def load_body(slug: str) -> str | None:
    return BODIES.get(slug)


# --- paragraphs ------------------------------------------------------------------


def test_paragraphs_splits_on_blank_lines_and_drops_empties():
    body = "First para.\n\nSecond para.\n\n  \n\nThird para."
    assert rr.paragraphs(body) == ["First para.", "Second para.", "Third para."]


def test_paragraphs_none_or_blank_is_empty_list():
    assert rr.paragraphs(None) == []
    assert rr.paragraphs("   \n\n  ") == []


def test_reading_time_minutes_rounds_up_from_word_count():
    # ~200 wpm; 800 words -> 4 min, 1 word -> 1 min (never 0 for a real article)
    assert rr.reading_time_minutes(800) == 4
    assert rr.reading_time_minutes(1) == 1
    assert rr.reading_time_minutes(0) == 0


# --- build_reading_room ----------------------------------------------------------


def test_build_orders_newest_first_and_excludes_undated(articles):
    room = rr.build_reading_room(articles, load_body=load_body)
    slugs = [e["slug"] for e in room["entries"]]
    assert slugs == ["inflation-returns", "bitcoin-is-a-signal", "the-fed-is-late"]
    assert "george-calhoun" not in slugs  # undated author-listing page dropped
    assert room["count"] == 3


def test_build_entry_carries_theme_body_and_reading_time(articles):
    room = rr.build_reading_room(articles, load_body=load_body)
    entry = next(e for e in room["entries"] if e["slug"] == "bitcoin-is-a-signal")
    assert entry["title"] == "Bitcoin Is A Signal"
    assert entry["theme"] == "Crypto / Bitcoin / Blockchain"
    assert entry["url"] == "https://www.forbes.com/b1/"
    assert entry["paragraphs"] == ["First para about bitcoin.", "Second para.", "Third para."]
    assert entry["reading_minutes"] == rr.reading_time_minutes(1200)


def test_build_links_prev_and_next_by_reading_order(articles):
    room = rr.build_reading_room(articles, load_body=load_body)
    entries = {e["slug"]: e for e in room["entries"]}
    # order: inflation-returns(newest) -> bitcoin-is-a-signal -> the-fed-is-late(oldest)
    assert entries["inflation-returns"]["prev_slug"] is None
    assert entries["inflation-returns"]["next_slug"] == "bitcoin-is-a-signal"
    assert entries["bitcoin-is-a-signal"]["prev_slug"] == "inflation-returns"
    assert entries["bitcoin-is-a-signal"]["next_slug"] == "the-fed-is-late"
    assert entries["the-fed-is-late"]["next_slug"] is None


def test_build_skips_articles_with_no_body(articles):
    # A dated, themed article whose raw file is missing must not appear (nothing to read).
    def partial_body(slug: str) -> str | None:
        return None if slug == "the-fed-is-late" else BODIES.get(slug)

    room = rr.build_reading_room(articles, load_body=partial_body)
    slugs = [e["slug"] for e in room["entries"]]
    assert slugs == ["inflation-returns", "bitcoin-is-a-signal"]
    assert room["entries"][0]["prev_slug"] is None
    assert room["entries"][-1]["next_slug"] is None


def test_build_limit_keeps_the_newest_n(articles):
    room = rr.build_reading_room(articles, load_body=load_body, limit=2)
    assert [e["slug"] for e in room["entries"]] == ["inflation-returns", "bitcoin-is-a-signal"]
    assert room["count"] == 2


def test_build_empty_when_no_articles():
    room = rr.build_reading_room([], load_body=load_body)
    assert room == {"entries": [], "count": 0, "themes": []}


def test_build_themes_are_present_sorted_by_frequency(articles):
    room = rr.build_reading_room(articles, load_body=load_body)
    # Fed/Inflation has 2 readable articles, Crypto has 1 -> Fed first, ties alphabetical
    assert room["themes"] == ["Fed / Inflation / Rates", "Crypto / Bitcoin / Blockchain"]
