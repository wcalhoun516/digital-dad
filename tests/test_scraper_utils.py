"""Characterization tests for scraper/utils.py pure helpers."""

from scraper.utils import is_article_url, normalize_url, slugify


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


class TestNormalizeUrl:
    def test_strips_query_and_fragment_and_adds_trailing_slash(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug?utm=x#top"
        expected = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(url) == expected

    def test_idempotent(self):
        url = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/slug/"
        assert normalize_url(normalize_url(url)) == normalize_url(url)
