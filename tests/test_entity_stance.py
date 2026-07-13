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
