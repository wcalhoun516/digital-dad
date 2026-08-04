"""Tests for analysis.entity_aliases — surface-form canonicalization (roadmap #14).

Pure and offline: `canonicalize` maps the many spellings the spaCy extractor emits for the
same subject (``the Federal Reserve`` / ``The Federal Reserve`` / ``Fed``) onto one display
name, so downstream builders (entity_graph, and later entity_stance / contradictions) stop
splitting one subject across several nodes. No corpus, no network.
"""

import pytest

from analysis import entity_aliases as ea


class TestStripLeadingThe:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("the Federal Reserve", "Federal Reserve"),
            ("The Federal Reserve", "Federal Reserve"),
            ("the New York Stock Exchange", "New York Stock Exchange"),
            ("The Senate", "Senate"),
        ],
    )
    def test_strips_a_single_leading_the(self, raw, expected):
        # These names have no alias entry, so their canonical form is just the-stripped.
        assert ea.canonicalize(raw) == expected

    def test_the_prefixed_alias_still_maps(self):
        # Strip THEN map: "The Fed" -> "Fed" -> canonical.
        assert ea.canonicalize("The Fed") == "Federal Reserve"

    def test_does_not_strip_the_mid_name(self):
        assert ea.canonicalize("Bank of the West") == "Bank of the West"

    def test_the_alone_is_left_untouched(self):
        # Stripping would empty the name; keep it (it'll be filtered elsewhere).
        assert ea.canonicalize("The") == "The"


class TestCuratedAliases:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Fed", "Federal Reserve"),
            ("the Fed", "Federal Reserve"),
            ("Federal Reserve", "Federal Reserve"),
            ("The Federal Reserve", "Federal Reserve"),
            ("Treasurys", "Treasury"),
            ("Treasury", "Treasury"),
            ("COVID", "Covid"),
            ("Covid-19", "Covid"),
            ("Powell", "Jerome Powell"),
            ("Jerome Powell", "Jerome Powell"),
            ("Ma", "Jack Ma"),
            ("Jack Ma", "Jack Ma"),
            ("BLS", "Bureau of Labor Statistics"),
            ("the Bureau of Labor Statistics", "Bureau of Labor Statistics"),
        ],
    )
    def test_maps_known_variants_to_canonical(self, raw, expected):
        assert ea.canonicalize(raw) == expected

    def test_alias_lookup_is_case_insensitive(self):
        assert ea.canonicalize("fed") == "Federal Reserve"
        assert ea.canonicalize("FED") == "Federal Reserve"


class TestPassthrough:
    def test_unknown_name_returns_whitespace_normalized_original(self):
        assert ea.canonicalize("Warren   Buffett") == "Warren Buffett"
        assert ea.canonicalize("  Tesla  ") == "Tesla"

    def test_unknown_name_preserves_casing(self):
        assert ea.canonicalize("InterDigital Communications") == "InterDigital Communications"

    def test_empty_or_blank_returns_empty(self):
        assert ea.canonicalize("") == ""
        assert ea.canonicalize("   ") == ""


class TestPossessive:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Federal Reserve’s", "Federal Reserve"),  # curly apostrophe
            ("Federal Reserve's", "Federal Reserve"),        # straight apostrophe
            ("Fed’s", "Federal Reserve"),               # possessive + alias
            ("Tesla's", "Tesla"),
        ],
    )
    def test_strips_trailing_possessive(self, raw, expected):
        assert ea.canonicalize(raw) == expected

    def test_bare_apostrophe_name_is_not_emptied(self):
        assert ea.canonicalize("'s") == "'s"


class TestAliasMapHygiene:
    def test_canonical_values_are_stable_under_reapplication(self):
        # Canonicalizing an already-canonical name must be a fixed point (idempotent),
        # otherwise merging could oscillate.
        for canonical in set(ea.ALIASES.values()):
            assert ea.canonicalize(canonical) == canonical

    def test_keys_are_lowercase(self):
        assert all(k == k.lower() for k in ea.ALIASES)
