"""Tests for analysis/linguistic.py — the dashboard's Linguistic Fingerprint builder.

Two long-standing defects motivated this file (both measured on the real 176-article
corpus before the fix):

* the sentence-length histogram capped its bins at 100 words and used half-open ``[a, b)``
  bins, so every sentence at or beyond the last edge was counted in **no bin** — 54 of the
  corpus's sentences (the longest, up to 286 words) simply vanished from the chart;
* ``_split_sentences`` cut on any period followed by a capital, so ``Ms. Lagarde`` /
  ``Prof. Calhoun`` / ``Federal Reserve Inc. Mark`` became two "sentences" apiece — 122 bad
  splits — inflating ``sentence_count`` and biasing avg sentence length, Flesch-Kincaid and
  Gunning Fog.
"""

import pytest

from analysis.linguistic import (
    _split_sentences,
    analyze_article,
    sentence_length_histogram,
)


class TestSentenceLengthHistogram:
    """Every sentence must land in exactly one bin — the chart is a partition."""

    def test_counts_sum_to_the_number_of_sentences(self):
        lengths = [1, 4, 7, 12, 22, 39, 101, 286]
        hist = sentence_length_histogram(lengths)
        assert sum(b["count"] for b in hist) == len(lengths)

    def test_long_tail_is_not_dropped(self):
        """A 286-word run-on used to be counted nowhere; it must now be represented."""
        hist = sentence_length_histogram([3, 286])
        assert sum(b["count"] for b in hist) == 2
        assert any(b["count"] == 1 and b["bin_start"] >= 100 for b in hist)

    def test_bins_are_contiguous_five_wide_from_zero(self):
        hist = sentence_length_histogram([2, 8, 33])
        assert hist[0]["bin_start"] == 0
        for prev, cur in zip(hist, hist[1:]):
            assert prev["bin_end"] == cur["bin_start"]
        assert all(b["bin_end"] - b["bin_start"] == 5 for b in hist[:-1])

    def test_value_on_a_bin_edge_falls_in_the_upper_bin(self):
        hist = sentence_length_histogram([5])
        placed = [b for b in hist if b["count"]]
        assert len(placed) == 1
        assert placed[0]["bin_start"] == 5

    def test_empty_input_returns_no_bins(self):
        assert sentence_length_histogram([]) == []


class TestSplitSentencesAbbreviations:
    """A period inside a known abbreviation is not a sentence boundary."""

    @pytest.mark.parametrize("abbrev_text", [
        "The ECB followed suit. Ms. Lagarde recanted, with almost verbatim language.",
        "He is the author of the book. Prof. Calhoun can be contacted at his office.",
        "It behaves like a bank in the real economy: the Federal Reserve Inc. Mark this well.",
        "She photographed the abbey at Mont St. Michel in the north of France last spring.",
    ])
    def test_does_not_split_inside_an_abbreviation(self, abbrev_text):
        for sentence in _split_sentences(abbrev_text):
            assert not sentence.endswith(("Ms.", "Prof.", "Inc.", "St.")), sentence

    def test_splitting_does_not_delete_words(self):
        """The orphan half of a bad split (``Ms.``) was under the >10-char floor, so the
        text was dropped outright — losing content *and* biasing every length metric."""
        text = "The ECB followed suit. Ms. Lagarde recanted the guidance almost verbatim."
        kept = " ".join(_split_sentences(text)).split()
        assert kept == text.split()

    def test_still_splits_a_real_sentence_boundary(self):
        sentences = _split_sentences(
            "The Fed raised rates again. Markets fell sharply the following morning."
        )
        assert len(sentences) == 2
        assert sentences[0].startswith("The Fed")
        assert sentences[1].startswith("Markets fell")

    def test_abbreviation_keeps_its_sentence_whole(self):
        sentences = _split_sentences(
            "Ms. Lagarde recanted the guidance. The market repriced immediately."
        )
        assert len(sentences) == 2
        assert sentences[0].startswith("Ms. Lagarde")


class TestAnalyzeArticleConsistency:
    def test_sentence_count_matches_the_split(self):
        body = "Ms. Lagarde spoke at length about policy. The market repriced immediately."
        metrics = analyze_article({"slug": "s", "date": "2024-01-01", "body": body})
        assert metrics["sentence_count"] == 2
        assert len(metrics["sentence_lengths"]) == 2

    def test_empty_body_yields_no_metrics(self):
        assert analyze_article({"slug": "s", "body": ""}) == {}
