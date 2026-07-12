"""Tests for analysis.calhoun_isms — quotable/aphoristic sentences per theme (roadmap #16).

Offline and deterministic: every test feeds small hand-built fixtures (corpus article dicts +
the shape of `themes.json`) to the pure helpers. No corpus, no network, no model calls.
"""

import pytest

from analysis import calhoun_isms as ci

# --- split_sentences --------------------------------------------------------

def test_split_sentences_basic():
    text = "The Fed is cautious. Bitcoin is volatile! Is gold really safe?"
    sents = ci.split_sentences(text)
    assert sents == [
        "The Fed is cautious.",
        "Bitcoin is volatile!",
        "Is gold really safe?",
    ]


def test_split_sentences_strips_and_drops_empty():
    text = "  One sentence here.   Another one there.  "
    assert ci.split_sentences(text) == ["One sentence here.", "Another one there."]


def test_split_sentences_empty_input():
    assert ci.split_sentences("") == []


# --- is_quotable ------------------------------------------------------------

def test_is_quotable_rejects_too_short():
    assert ci.is_quotable("Markets always overreact badly.", min_words=8) is False


def test_is_quotable_accepts_in_band():
    s = "Inflation is always ultimately a failure of political nerve today."
    assert ci.is_quotable(s, min_words=8, max_words=30) is True


def test_is_quotable_rejects_too_long():
    long = "Word " * 40 + "end."
    assert ci.is_quotable(long, max_words=30) is False


def test_is_quotable_rejects_questions():
    s = "Why does the central bank always lose its nerve when tested?"
    assert ci.is_quotable(s) is False


def test_is_quotable_rejects_dependent_opener():
    # A sentence that opens with a pronoun/conjunction needing an antecedent is not
    # self-contained enough to stand alone as an aphorism.
    for opener in ("But", "This", "It", "However", "They", "And"):
        s = f"{opener} the whole system depends on a fragile shared confidence today."
        assert ci.is_quotable(s) is False, opener


def test_is_quotable_rejects_urls_and_handles():
    s = "Read the whole argument at http://forbes.com/x for the complete story now."
    assert ci.is_quotable(s) is False


def test_is_quotable_requires_capitalized_start():
    s = "inflation is always ultimately a failure of political nerve in the end."
    assert ci.is_quotable(s) is False


# --- quotability_score ------------------------------------------------------

def test_score_rewards_aphoristic_markers():
    plain = "The bank raised rates by a quarter point at the meeting."
    aphoristic = "The market always punishes those who never respect its power."
    assert ci.quotability_score(aphoristic) > ci.quotability_score(plain)


def test_score_penalizes_attribution():
    plain = "The system rewards patience and punishes fear over the long run."
    reported = "The system rewards patience, Powell said, over the long run."
    assert ci.quotability_score(reported) < ci.quotability_score(plain)


def test_score_is_deterministic():
    s = "Inflation is always a failure of political nerve at its core."
    assert ci.quotability_score(s) == ci.quotability_score(s)


# --- extract_isms -----------------------------------------------------------

@pytest.fixture
def themes_data():
    return {
        "num_clusters": 2,
        "clusters": [
            {"id": 0, "label": "Fed / Rates"},
            {"id": 1, "label": "Crypto / Bitcoin"},
        ],
        "articles": [
            {"slug": "fed-nerve", "cluster_id": 0, "cluster_label": "Fed / Rates"},
            {"slug": "btc-truth", "cluster_id": 1, "cluster_label": "Crypto / Bitcoin"},
        ],
    }


@pytest.fixture
def articles():
    return [
        {
            "slug": "fed-nerve",
            "title": "The Fed's Nerve",
            "date": "2021-05-01",
            "body": (
                "Inflation is always ultimately a failure of political nerve at its core. "
                "The central bank raised rates by a quarter point at its June meeting."
            ),
        },
        {
            "slug": "btc-truth",
            "title": "Bitcoin's Truth",
            "date": "2022-03-01",
            "body": (
                "Bitcoin is nothing more than a mirror held up to our collective anxiety. "
                "It traded near thirty thousand dollars on Tuesday afternoon in New York."
            ),
        },
    ]


def test_extract_isms_groups_by_theme(articles, themes_data):
    result = ci.extract_isms(articles, themes_data, top_n=5)
    themes = {t["theme"]: t for t in result["themes"]}
    assert set(themes) == {"Fed / Rates", "Crypto / Bitcoin"}
    fed = themes["Fed / Rates"]["isms"]
    assert fed[0]["text"].startswith("Inflation is always")
    assert fed[0]["slug"] == "fed-nerve"
    assert fed[0]["title"] == "The Fed's Nerve"
    assert fed[0]["date"] == "2021-05-01"


def test_extract_isms_sorted_by_score_and_capped(articles, themes_data):
    result = ci.extract_isms(articles, themes_data, top_n=1)
    for theme in result["themes"]:
        assert len(theme["isms"]) <= 1
        scores = [i["score"] for i in theme["isms"]]
        assert scores == sorted(scores, reverse=True)


def test_extract_isms_overall_top(articles, themes_data):
    result = ci.extract_isms(articles, themes_data, top_n=5)
    overall = result["overall_top"]
    assert overall, "expected a non-empty overall board"
    scores = [i["score"] for i in overall]
    assert scores == sorted(scores, reverse=True)
    # Each overall entry carries its source theme for context.
    assert all("theme" in i for i in overall)


def test_extract_isms_dedupes_identical_sentences(themes_data):
    dup = "The market always punishes those who never respect its raw power."
    arts = [
        {"slug": "fed-nerve", "title": "A", "date": "2021-01-01", "body": f"{dup} {dup}"},
    ]
    result = ci.extract_isms(arts, themes_data, top_n=10)
    fed = next(t for t in result["themes"] if t["theme"] == "Fed / Rates")
    texts = [i["text"] for i in fed["isms"]]
    assert texts.count(dup) == 1


def test_extract_isms_skips_articles_without_theme(articles, themes_data):
    orphan = {
        "slug": "no-theme",
        "title": "Orphan",
        "date": "2020-01-01",
        "body": "Every crisis is always a chance to relearn an old and painful truth.",
    }
    result = ci.extract_isms(articles + [orphan], themes_data, top_n=5)
    all_slugs = {i["slug"] for t in result["themes"] for i in t["isms"]}
    assert "no-theme" not in all_slugs


# --- run (I/O wrapper) ------------------------------------------------------

def test_run_returns_structure_without_writing(articles, themes_data):
    result = ci.run(articles=articles, themes_data=themes_data, write=False)
    assert result["meta"]["num_themes"] == 2
    assert result["meta"]["total_articles"] == 2
    assert "themes" in result and "overall_top" in result


def test_render_markdown_smoke(articles, themes_data):
    result = ci.run(articles=articles, themes_data=themes_data, write=False)
    md = ci.render_markdown(result)
    assert "Calhoun-isms" in md
    assert "Fed / Rates" in md
