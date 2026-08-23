"""Characterization tests for scraper/utils.py pure helpers."""

import pytest

from scraper.utils import is_article_url, normalize_url, slugify

BASE = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/"


class TestSlugify:
    def test_lowercases_and_hyphenates_spaces(self):
        assert slugify("Hello World") == "hello-world"

    def test_strips_punctuation(self):
        assert slugify("The Fed Is Wrong!") == "the-fed-is-wrong"

    def test_collapses_whitespace_and_separators(self):
        assert slugify("Multiple   spaces") == "multiple-spaces"
        assert slugify("foo_bar") == "foo-bar"

    def test_strips_leading_and_trailing_separators(self):
        assert slugify("  -- trimmed -- ") == "trimmed"

    def test_idempotent(self):
        once = slugify("Some Messy Title!! Here")
        assert slugify(once) == once

    def test_respects_max_length(self):
        assert len(slugify("a" * 200, max_length=10)) == 10

    def test_preserves_unicode_word_chars(self):
        assert slugify("Café Münchën") == "café-münchën"


class TestIsArticleUrl:
    def test_accepts_georgecalhoun_article(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/"
        assert is_article_url(url) is True

    def test_rejects_amp_variant(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/amp/"
        assert is_article_url(url) is False

    def test_rejects_other_author(self):
        url = "https://www.forbes.com/sites/someoneelse/2024/01/15/a-slug/"
        assert is_article_url(url) is False

    def test_rejects_author_listing_page(self):
        url = "https://www.forbes.com/sites/georgecalhoun/"
        assert is_article_url(url) is False

    def test_rejects_pagination_path(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2"
        assert is_article_url(url) is False


class TestIsArticleUrlAmpSegment:
    """The `/amp` filter must match a path *segment*, not a bare substring.

    A substring test discards every article whose slug merely begins with "amp" —
    "Ampere", "Amplify", "Ample" — which is silent, unlogged corpus loss.
    """

    @pytest.mark.parametrize(
        "slug",
        [
            "ampere-computing-and-the-arm-server-market",
            "amplify-etfs-bet-on-semiconductors",
            "ample-reserves-and-the-fed",
            "amplified-inflation-is-still-inflation",
            "amped-up-expectations-at-the-ecb",
            "amputating-the-supply-chain",
        ],
    )
    def test_accepts_slug_beginning_with_amp(self, slug):
        assert is_article_url(BASE + slug + "/") is True

    @pytest.mark.parametrize(
        "url",
        [
            BASE + "the-fed-is-wrong/amp/",
            BASE + "the-fed-is-wrong/amp",
            "https://www.forbes.com/sites/georgecalhoun/amp/the-fed-is-wrong/",
        ],
    )
    def test_still_rejects_real_amp_segments(self, url):
        assert is_article_url(url) is False

    @pytest.mark.parametrize("variant", ["AMP", "Amp"])
    def test_rejects_amp_segment_case_insensitively(self, variant):
        """A case variant is the same duplicate page, not a distinct article."""
        assert is_article_url(f"{BASE}the-fed-is-wrong/{variant}/") is False

    def test_accepts_slug_that_merely_contains_amp(self):
        assert is_article_url(BASE + "why-ample-reserves-broke-the-market/") is True

    def test_amp_prefixed_slug_survives_normalization(self):
        """The gate and the normalizer must agree on an amp-prefixed article."""
        url = BASE + "ampere-computing-and-the-arm-server-market/?utm_source=x"
        assert is_article_url(url) is True
        assert is_article_url(normalize_url(url)) is True


class TestNormalizeUrl:
    def test_strips_query_and_fragment_and_adds_trailing_slash(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug?utm=x#top"
        expected = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(url) == expected

    def test_idempotent(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(normalize_url(url)) == normalize_url(url)


class TestNormalizeUrlCasing:
    """Scheme and host are case-insensitive (RFC 3986 §3.1, §3.2.2).

    Discovery feeds `normalize_url` raw strings from sitemaps and the Wayback CDX index.
    If two spellings of the same host produce two different strings, the manifest gains a
    URL-variant twin and the scraper re-fetches an article it already has.
    """

    def test_lowercases_host(self):
        url = "https://WWW.Forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(url) == BASE + "slug/"

    def test_lowercases_scheme(self):
        url = "HTTPS://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(url) == BASE + "slug/"

    def test_host_case_variants_collapse_to_one_url(self):
        variants = [
            "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/",
            "https://WWW.FORBES.COM/sites/georgecalhoun/2024/01/15/slug/",
            "HTTPS://Www.Forbes.Com/sites/georgecalhoun/2024/01/15/slug?utm=x",
        ]
        assert len({normalize_url(u) for u in variants}) == 1

    def test_preserves_path_case(self):
        """Only scheme and host are case-insensitive — the path identifies the article."""
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/Slug-With-Caps/"
        assert normalize_url(url).endswith("/Slug-With-Caps/")

    def test_idempotent_on_mixed_case(self):
        url = "HTTPS://WWW.Forbes.com/sites/georgecalhoun/2024/01/15/slug?a=1#top"
        assert normalize_url(normalize_url(url)) == normalize_url(url)
