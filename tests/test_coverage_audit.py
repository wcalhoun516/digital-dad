"""Tests for scraper/coverage_audit.py — coverage audit vs the author index (roadmap #9)."""

from scraper.coverage_audit import (
    audit_coverage,
    parse_article_url,
)


AUTHOR = "https://www.forbes.com/sites/georgecalhoun"


def _url(date: str, slug: str) -> str:
    """Build an author article URL from an ISO date and slug."""
    y, m, d = date.split("-")
    return f"{AUTHOR}/{y}/{m}/{d}/{slug}/"


def _manifest_articles(*pairs):
    """pairs of (date, slug) → manifest-shaped article dicts."""
    return [{"slug": slug, "date": date, "url": _url(date, slug)} for date, slug in pairs]


class TestParseArticleUrl:
    def test_parses_date_month_year_and_slug(self):
        info = parse_article_url(f"{AUTHOR}/2020/05/26/europes-hamiltonian-moment/")
        assert info is not None
        assert info["date"] == "2020-05-26"
        assert info["year"] == "2020"
        assert info["month"] == "2020-05"
        assert info["slug"] == "europes-hamiltonian-moment"

    def test_url_key_is_scheme_and_www_insensitive(self):
        a = parse_article_url("http://www.forbes.com/sites/georgecalhoun/2021/01/02/foo/")
        b = parse_article_url("https://forbes.com/sites/georgecalhoun/2021/01/02/foo/")
        assert a is not None and b is not None
        assert a["key"] == b["key"]

    def test_url_key_ignores_query_and_fragment(self):
        a = parse_article_url(f"{AUTHOR}/2021/01/02/foo/")
        b = parse_article_url(f"{AUTHOR}/2021/01/02/foo/?utm=x#top")
        assert a["key"] == b["key"]

    def test_non_author_url_returns_none(self):
        assert parse_article_url("https://www.forbes.com/sites/someoneelse/2021/01/02/foo/") is None

    def test_url_without_date_returns_none(self):
        assert parse_article_url(f"{AUTHOR}/some-listing-page/") is None

    def test_empty_or_garbage_returns_none(self):
        assert parse_article_url("") is None
        assert parse_article_url("not a url") is None


class TestAuditCoverage:
    def test_full_coverage_is_ok(self):
        arts = _manifest_articles(("2020-05-26", "a"), ("2020-06-10", "b"))
        discovered = [_url("2020-05-26", "a"), _url("2020-06-10", "b")]
        report = audit_coverage(arts, discovered)
        assert report["ok"] is True
        assert report["missing_count"] == 0
        assert report["missing_urls"] == []
        assert report["coverage_ratio"] == 1.0
        assert report["gap_months"] == []

    def test_missing_url_is_reported_with_date_and_month(self):
        arts = _manifest_articles(("2020-05-26", "a"))
        discovered = [_url("2020-05-26", "a"), _url("2020-07-01", "gap")]
        report = audit_coverage(arts, discovered)
        assert report["ok"] is False
        assert report["missing_count"] == 1
        miss = report["missing_urls"][0]
        assert miss["slug"] == "gap"
        assert miss["date"] == "2020-07-01"
        assert miss["month"] == "2020-07"
        assert miss["url"] == _url("2020-07-01", "gap")
        assert "2020-07" in report["gap_months"]

    def test_missing_urls_sorted_by_date_then_slug(self):
        arts = _manifest_articles()
        discovered = [
            _url("2021-03-02", "z"),
            _url("2021-01-05", "b"),
            _url("2021-01-05", "a"),
        ]
        report = audit_coverage(arts, discovered)
        got = [(m["date"], m["slug"]) for m in report["missing_urls"]]
        assert got == [("2021-01-05", "a"), ("2021-01-05", "b"), ("2021-03-02", "z")]

    def test_by_month_counts_have_discovered_missing(self):
        arts = _manifest_articles(("2020-05-26", "a"))
        discovered = [_url("2020-05-26", "a"), _url("2020-05-30", "b")]
        report = audit_coverage(arts, discovered)
        assert report["by_month"]["2020-05"] == {"have": 1, "discovered": 2, "missing": 1}

    def test_coverage_ratio_is_matched_over_discovered(self):
        arts = _manifest_articles(("2020-05-26", "a"))
        discovered = [_url("2020-05-26", "a"), _url("2020-06-01", "b"), _url("2020-06-02", "c")]
        report = audit_coverage(arts, discovered)
        assert report["discovered_count"] == 3
        assert report["matched_count"] == 1
        assert round(report["coverage_ratio"], 3) == round(1 / 3, 3)

    def test_variant_scheme_and_query_dedup_to_one_discovered(self):
        arts = _manifest_articles(("2020-05-26", "a"))
        discovered = [
            "http://www.forbes.com/sites/georgecalhoun/2020/05/26/a/",
            "https://forbes.com/sites/georgecalhoun/2020/05/26/a/?utm=x",
        ]
        report = audit_coverage(arts, discovered)
        assert report["discovered_count"] == 1
        assert report["missing_count"] == 0

    def test_extra_urls_in_manifest_not_discovered(self):
        arts = _manifest_articles(("2020-05-26", "a"), ("2020-05-27", "extra"))
        discovered = [_url("2020-05-26", "a")]
        report = audit_coverage(arts, discovered)
        assert report["extra_count"] == 1
        assert report["extra_urls"][0]["slug"] == "extra"

    def test_unparsed_urls_are_collected_not_counted(self):
        arts = [{"slug": "weird", "date": "2020-01-01", "url": "https://example.com/x/"}]
        discovered = [_url("2020-05-26", "a"), "https://web.archive.org/nonsense"]
        report = audit_coverage(arts, discovered)
        assert report["have_count"] == 0
        assert report["discovered_count"] == 1
        assert "https://example.com/x/" in report["unparsed_manifest_urls"]
        assert "https://web.archive.org/nonsense" in report["unparsed_discovered_urls"]

    def test_empty_discovered_is_ok_and_ratio_one(self):
        arts = _manifest_articles(("2020-05-26", "a"))
        report = audit_coverage(arts, [])
        assert report["ok"] is True
        assert report["missing_count"] == 0
        assert report["coverage_ratio"] == 1.0
