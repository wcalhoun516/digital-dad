"""Tests for scraper.__main__.upsert_article — the root-cause fix for #8's duplicate
slugs. The scraper used to match existing manifest entries by URL, so an article
rediscovered under a URL variant appended a second same-slug entry. upsert_article
matches on slug instead."""

from scraper.__main__ import upsert_article


def _entry(slug, url):
    return {"slug": slug, "url": url, "title": slug}


class TestUpsertArticle:
    def test_appends_a_new_slug(self):
        articles = []
        upsert_article(articles, _entry("alpha", "https://a/"))
        assert articles == [_entry("alpha", "https://a/")]

    def test_replaces_entry_with_same_slug_under_a_different_url(self):
        articles = [_entry("alpha", "http://a/")]
        upsert_article(articles, _entry("alpha", "https://a/?sh=x"))
        assert len(articles) == 1
        assert articles[0]["url"] == "https://a/?sh=x"

    def test_does_not_append_a_second_entry_for_the_same_slug(self):
        articles = [_entry("alpha", "http://a/")]
        upsert_article(articles, _entry("alpha", "https://a/variant"))
        assert [a["slug"] for a in articles] == ["alpha"]

    def test_replaces_in_place_preserving_position(self):
        articles = [_entry("a", "u1"), _entry("b", "u2"), _entry("c", "u3")]
        upsert_article(articles, _entry("b", "u2-new"))
        assert [a["slug"] for a in articles] == ["a", "b", "c"]
        assert articles[1]["url"] == "u2-new"

    def test_distinct_slugs_all_appended(self):
        articles = []
        upsert_article(articles, _entry("a", "u1"))
        upsert_article(articles, _entry("b", "u2"))
        assert [a["slug"] for a in articles] == ["a", "b"]
