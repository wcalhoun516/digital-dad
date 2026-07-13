"""Tests for analysis.entity_stance — per-entity stance over time (roadmap #17).

Offline and deterministic: the pure helpers are exercised on tiny hand-built strings and
`per_article` / article fixtures. No corpus, no network, no conductor.
"""

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
