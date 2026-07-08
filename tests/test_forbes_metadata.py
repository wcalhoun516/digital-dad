"""Tests for the richer per-article metadata helpers in scraper/forbes_requests.py.

These cover the pure HTML→metadata extraction (roadmap #10): canonical URL,
published-vs-modified date, section, and byline variants. All fixtures are inline
HTML strings parsed with BeautifulSoup, so the suite stays fully offline.
"""

from bs4 import BeautifulSoup

from scraper.forbes_requests import extract_metadata

ARTICLE_URL = "https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


class TestCanonicalUrl:
    def test_prefers_link_rel_canonical(self):
        html = """
        <html><head>
          <link rel="canonical" href="https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/">
          <meta property="og:url" content="https://www.forbes.com/other/">
        </head></html>
        """
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["canonical_url"] == (
            "https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/"
        )

    def test_falls_back_to_og_url(self):
        html = """
        <html><head>
          <meta property="og:url" content="https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/">
        </head></html>
        """
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["canonical_url"].endswith("/the-fed-is-wrong/")

    def test_resolves_relative_canonical_against_page_url(self):
        html = '<link rel="canonical" href="/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/">'
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["canonical_url"] == (
            "https://www.forbes.com/sites/georgecalhoun/2024/01/15/the-fed-is-wrong/"
        )

    def test_falls_back_to_page_url_when_absent(self):
        md = extract_metadata(_soup("<html><head></head></html>"), ARTICLE_URL)
        assert md["canonical_url"] == ARTICLE_URL


class TestDates:
    def test_published_from_article_published_time(self):
        html = '<meta property="article:published_time" content="2024-01-15T09:30:00-05:00">'
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["published_date"] == "2024-01-15T09:30:00-05:00"

    def test_published_falls_back_to_time_tag_then_url(self):
        html = '<time datetime="2024-01-15T09:30:00Z">Jan 15</time>'
        assert extract_metadata(_soup(html), ARTICLE_URL)["published_date"] == (
            "2024-01-15T09:30:00Z"
        )
        # No signal in HTML at all → derive date from the URL path.
        md = extract_metadata(_soup("<html></html>"), ARTICLE_URL)
        assert md["published_date"] == "2024-01-15"

    def test_modified_from_article_modified_time(self):
        html = (
            '<meta property="article:published_time" content="2024-01-15T09:30:00Z">'
            '<meta property="article:modified_time" content="2024-01-18T14:00:00Z">'
        )
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["updated_date"] == "2024-01-18T14:00:00Z"

    def test_modified_falls_back_to_og_updated_time(self):
        html = '<meta property="og:updated_time" content="2024-02-01T00:00:00Z">'
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["updated_date"] == "2024-02-01T00:00:00Z"

    def test_modified_empty_when_absent(self):
        html = '<meta property="article:published_time" content="2024-01-15T09:30:00Z">'
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["updated_date"] == ""


class TestSection:
    def test_section_from_meta(self):
        html = '<meta property="article:section" content="Money">'
        assert extract_metadata(_soup(html), ARTICLE_URL)["section"] == "Money"

    def test_section_from_breadcrumb_fallback(self):
        html = """
        <nav class="breadcrumbs">
          <a href="/">Forbes</a>
          <a href="/money/">Money</a>
          <a href="/money/markets/">Markets</a>
        </nav>
        """
        assert extract_metadata(_soup(html), ARTICLE_URL)["section"] == "Markets"

    def test_section_empty_when_absent(self):
        assert extract_metadata(_soup("<html></html>"), ARTICLE_URL)["section"] == ""


class TestBylines:
    def test_primary_byline_from_meta_author(self):
        html = '<meta name="author" content="George Calhoun">'
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["byline"] == "George Calhoun"
        assert md["byline_variants"] == ["George Calhoun"]

    def test_collects_distinct_variants_in_order(self):
        html = """
        <meta name="author" content="George Calhoun">
        <a rel="author" href="/x">George Calhoun, Contributor</a>
        <span class="author-name">George Calhoun</span>
        """
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["byline"] == "George Calhoun"
        assert md["byline_variants"] == ["George Calhoun", "George Calhoun, Contributor"]

    def test_ignores_url_valued_article_author(self):
        html = """
        <meta property="article:author" content="https://www.forbes.com/sites/georgecalhoun/">
        <meta name="author" content="George Calhoun">
        """
        md = extract_metadata(_soup(html), ARTICLE_URL)
        assert md["byline_variants"] == ["George Calhoun"]

    def test_empty_when_no_author(self):
        md = extract_metadata(_soup("<html></html>"), ARTICLE_URL)
        assert md["byline"] == ""
        assert md["byline_variants"] == []


class TestExtractMetadataShape:
    def test_returns_all_expected_keys(self):
        md = extract_metadata(_soup("<html></html>"), ARTICLE_URL)
        assert set(md) == {
            "canonical_url",
            "published_date",
            "updated_date",
            "section",
            "byline",
            "byline_variants",
        }
