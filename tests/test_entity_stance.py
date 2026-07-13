"""Tests for analysis.entity_stance — per-entity stance over time (roadmap #17).

Offline and deterministic: the pure helpers are exercised on tiny hand-built strings and
`per_article` / article fixtures. No corpus, no network, no conductor.
"""

import pytest

from analysis import entity_stance as es

# --- sentence_polarity ------------------------------------------------------

def test_polarity_positive_words_score_positive():
    assert es.sentence_polarity("This was a great success and a strong recovery.") > 0


def test_polarity_negative_words_score_negative():
    assert es.sentence_polarity("It ended in failure, collapse, and crisis.") < 0


def test_polarity_neutral_sentence_is_zero():
    assert es.sentence_polarity("The meeting was held on Tuesday afternoon.") == 0


def test_polarity_negation_flips_positive():
    # "not a success" should not read as positive.
    assert es.sentence_polarity("It was not a success.") < 0


def test_polarity_negation_flips_negative():
    # "no failure" should not read as negative.
    assert es.sentence_polarity("There was no failure here.") > 0


def test_polarity_is_case_insensitive():
    assert es.sentence_polarity("A STRONG, SUCCESSFUL outcome.") > 0


def test_polarity_negator_within_window_flips():
    assert es.sentence_polarity("It was not really a success.") < 0


def test_polarity_negator_outside_window_does_not_flip():
    # "No" is >3 tokens before "success", so it must not flip it.
    assert es.sentence_polarity("No, the outcome was clearly a success.") > 0


# --- entity_mentioned -------------------------------------------------------

def test_entity_mentioned_word_boundary():
    assert es.entity_mentioned("The Fed raised rates.", "Fed")
    # "Fed" must not match inside "federal".
    assert not es.entity_mentioned("A federal program launched.", "Fed")


def test_entity_mentioned_case_insensitive_multiword():
    assert es.entity_mentioned("He praised the federal reserve today.", "Federal Reserve")


def test_entity_mentioned_absent():
    assert not es.entity_mentioned("Bitcoin surged overnight.", "Powell")


# --- article_stance ---------------------------------------------------------

def test_article_stance_averages_mentioning_sentences():
    body = (
        "The Fed engineered a strong recovery. "  # +1, mentions Fed
        "Bitcoin remains a dangerous bubble. "     # not about Fed
        "The Fed's policy was a success."          # +1, mentions Fed
    )
    stance = es.article_stance(body, "Fed")
    assert stance["n_sentences"] == 2
    assert stance["mean_stance"] > 0


def test_article_stance_no_mentions_returns_none():
    stance = es.article_stance("Bitcoin surged today.", "Powell")
    assert stance["n_sentences"] == 0
    assert stance["mean_stance"] is None


# --- build_stance -----------------------------------------------------------

@pytest.fixture
def articles():
    return [
        {"slug": "a1", "date": "2020-01-01", "title": "Early Fed",
         "body": "The Fed delivered a success. The Fed looked strong."},
        {"slug": "a2", "date": "2022-01-01", "title": "Later Fed",
         "body": "The Fed became a disaster. The Fed looked weak."},
        {"slug": "a3", "date": "2021-01-01", "title": "Byline",
         "body": "George Calhoun writes here. This is boilerplate."},
    ]


@pytest.fixture
def entities_data():
    return {
        "total_articles_analyzed": 3,
        "per_article": [
            {"slug": "a1", "date": "2020-01-01", "orgs": [["Fed", 4]], "people": []},
            {"slug": "a2", "date": "2022-01-01", "orgs": [["Fed", 4]], "people": []},
            {"slug": "a3", "date": "2021-01-01", "orgs": [],
             "people": [["George Calhoun", 2]]},
        ],
    }


def test_build_stance_tracks_yearly_trajectory(articles, entities_data):
    result = es.build_stance(articles, entities_data, min_articles=1)
    fed = next(e for e in result["entities"] if e["name"] == "Fed")
    years = {p["year"]: p["mean_stance"] for p in fed["trajectory"]}
    assert years["2020"] == 1.0
    assert years["2022"] == -1.0
    assert fed["article_count"] == 2


def test_build_stance_trend_is_cooling(articles, entities_data):
    result = es.build_stance(articles, entities_data, min_articles=1)
    fed = next(e for e in result["entities"] if e["name"] == "Fed")
    assert fed["trend"] == "cooling"
    assert fed["trend_delta"] == -2.0
    assert any(e["name"] == "Fed" for e in result["cooling"])


def test_build_stance_excludes_byline_boilerplate(articles, entities_data):
    result = es.build_stance(articles, entities_data, min_articles=1)
    assert all(e["name"] != "George Calhoun" for e in result["entities"])


def test_build_stance_excludes_photo_credit_boilerplate():
    # "Photo" is a Forbes image-credit artifact the extractor picks up, not a subject.
    articles = [{"slug": "p1", "date": "2020-01-01",
                 "body": "The Photo showed a strong scene."}]
    entities_data = {"per_article": [
        {"slug": "p1", "date": "2020-01-01", "orgs": [], "people": [["Photo", 3]]}]}
    result = es.build_stance(articles, entities_data, min_articles=1)
    assert all(e["name"] != "Photo" for e in result["entities"])


def test_build_stance_min_articles_filters(articles, entities_data):
    # Fed appears in 2 articles; require 3 -> dropped.
    result = es.build_stance(articles, entities_data, min_articles=3)
    assert result["entities"] == []


def test_build_stance_min_mentions_filters_entity():
    # Fed is mentioned only once in the extraction; require 2 -> it never counts.
    articles = [{"slug": "a1", "date": "2020-01-01",
                 "body": "The Fed looked strong today."}]
    entities_data = {"per_article": [
        {"slug": "a1", "date": "2020-01-01", "orgs": [["Fed", 1]], "people": []}]}
    result = es.build_stance(articles, entities_data, min_articles=1, min_mentions=2)
    assert result["entities"] == []


def test_build_stance_overall_is_sentence_weighted():
    # 2020 has 1 sentence (+1); 2021 has 3 sentences (-1 each). Sentence-weighted overall is
    # (1 - 3) / 4 = -0.5, NOT the mean-of-year-means (1 + -1)/2 = 0.
    articles = [
        {"slug": "a1", "date": "2020-01-01", "body": "The ECB looked strong."},
        {"slug": "a2", "date": "2021-01-01",
         "body": "The ECB failed. The ECB was weak. The ECB was a disaster."},
    ]
    entities_data = {"per_article": [
        {"slug": "a1", "date": "2020-01-01", "orgs": [["ECB", 3]], "people": []},
        {"slug": "a2", "date": "2021-01-01", "orgs": [["ECB", 3]], "people": []},
    ]}
    result = es.build_stance(articles, entities_data, min_articles=1)
    ecb = next(e for e in result["entities"] if e["name"] == "ECB")
    assert ecb["overall_stance"] == -0.5


# --- render_markdown / run --------------------------------------------------

def test_render_markdown_names_the_entity_and_trend(articles, entities_data):
    md = es.render_markdown(es.build_stance(articles, entities_data, min_articles=1))
    assert "Fed" in md
    assert "cooling" in md.lower()


def test_run_write_false_returns_without_io(articles, entities_data):
    result = es.run(articles=articles, entities_data=entities_data,
                    min_articles=1, write=False)
    assert result["meta"]["n_entities"] == 1
