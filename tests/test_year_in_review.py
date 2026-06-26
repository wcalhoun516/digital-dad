"""Tests for analysis/year_in_review.py — the annual digest builder + renderer.

Roadmap #23 (family). These cover the deterministic, offline pieces: filtering a year's
articles, ranking themes and notable predictions, assembling the digest, and rendering the
email. No conductor, network, or Gmail MCP is exercised here.
"""

import datetime

import pytest

from analysis.year_in_review import (
    articles_for_year,
    build_digest,
    default_year,
    notable_predictions,
    render_html,
    render_markdown,
    run,
    top_themes,
)

THEME_ARTICLES = [
    {"slug": "a", "title": "Inflation Is Back", "date": "2024-02-01",
     "word_count": 1200, "cluster_label": "Inflation / Cpi / Price"},
    {"slug": "b", "title": "The Fed Blinks", "date": "2024-06-15",
     "word_count": 900, "cluster_label": "Fed / Financial / Wireless"},
    {"slug": "c", "title": "CPI Again", "date": "2024-09-09",
     "word_count": 1100, "cluster_label": "Inflation / Cpi / Price"},
    {"slug": "d", "title": "Old News", "date": "2023-12-31",
     "word_count": 800, "cluster_label": "Fed / Financial / Wireless"},
    {"slug": "e", "title": "No Date Listing", "date": "",
     "word_count": 267, "cluster_label": "Fed / Financial / Wireless"},
]

PREDICTIONS = [
    {"claim": "Inflation will stay above 3% through 2024.", "topic": "inflation",
     "confidence_language": "confident", "article_date": "2024-02-01",
     "article_title": "Inflation Is Back",
     "article_url": "https://forbes.com/a"},
    {"claim": "The Fed will not cut before September.", "topic": "Fed policy",
     "confidence_language": "certain", "article_date": "2024-06-15",
     "article_title": "The Fed Blinks", "article_url": "https://forbes.com/b"},
    {"claim": "A hedged maybe.", "topic": "markets",
     "confidence_language": "hedged", "article_date": "2024-09-09",
     "article_title": "CPI Again", "article_url": "https://forbes.com/c"},
    {"claim": "Last year's call.", "topic": "oil",
     "confidence_language": "certain", "article_date": "2023-05-05",
     "article_title": "Old News", "article_url": "https://forbes.com/d"},
]


class TestArticlesForYear:
    def test_filters_to_the_requested_year(self):
        got = articles_for_year(THEME_ARTICLES, 2024)
        assert [a["slug"] for a in got] == ["a", "b", "c"]

    def test_accepts_year_as_string_or_int(self):
        assert articles_for_year(THEME_ARTICLES, "2024") == articles_for_year(
            THEME_ARTICLES, 2024
        )

    def test_excludes_empty_dates(self):
        slugs = [a["slug"] for a in articles_for_year(THEME_ARTICLES, 2024)]
        assert "e" not in slugs

    def test_empty_when_no_articles_match(self):
        assert articles_for_year(THEME_ARTICLES, 2099) == []


class TestTopThemes:
    def test_counts_by_cluster_label_descending(self):
        year = articles_for_year(THEME_ARTICLES, 2024)
        assert top_themes(year) == [
            {"label": "Inflation / Cpi / Price", "count": 2},
            {"label": "Fed / Financial / Wireless", "count": 1},
        ]

    def test_respects_top_n(self):
        year = articles_for_year(THEME_ARTICLES, 2024)
        assert top_themes(year, top_n=1) == [
            {"label": "Inflation / Cpi / Price", "count": 2}
        ]

    def test_ties_break_alphabetically(self):
        arts = [
            {"cluster_label": "Zeta"},
            {"cluster_label": "Alpha"},
        ]
        assert [t["label"] for t in top_themes(arts)] == ["Alpha", "Zeta"]

    def test_empty_input(self):
        assert top_themes([]) == []


class TestNotablePredictions:
    def test_filters_to_year_and_ranks_by_conviction(self):
        got = notable_predictions(PREDICTIONS, 2024)
        # 'certain' outranks 'confident' outranks 'hedged'; last-year call excluded.
        assert [p["claim"] for p in got] == [
            "The Fed will not cut before September.",
            "Inflation will stay above 3% through 2024.",
            "A hedged maybe.",
        ]

    def test_respects_limit(self):
        got = notable_predictions(PREDICTIONS, 2024, limit=1)
        assert len(got) == 1
        assert got[0]["confidence_language"] == "certain"

    def test_dedupes_identical_claims(self):
        dupes = PREDICTIONS + [dict(PREDICTIONS[0])]
        got = notable_predictions(dupes, 2024)
        claims = [p["claim"] for p in got]
        assert claims.count("Inflation will stay above 3% through 2024.") == 1

    def test_empty_when_no_predictions_in_year(self):
        assert notable_predictions(PREDICTIONS, 2099) == []


class TestBuildDigest:
    def test_assembles_the_full_digest(self):
        d = build_digest(THEME_ARTICLES, PREDICTIONS, 2024)
        assert d["year"] == 2024
        assert d["article_count"] == 3
        assert d["total_words"] == 1200 + 900 + 1100
        assert d["top_themes"][0]["label"] == "Inflation / Cpi / Price"
        assert d["notable_predictions"][0]["confidence_language"] == "certain"

    def test_empty_year_is_safe(self):
        d = build_digest(THEME_ARTICLES, PREDICTIONS, 2099)
        assert d["article_count"] == 0
        assert d["total_words"] == 0
        assert d["top_themes"] == []
        assert d["notable_predictions"] == []


class TestRenderers:
    def test_html_includes_headline_numbers(self):
        d = build_digest(THEME_ARTICLES, PREDICTIONS, 2024)
        html = render_html(d)
        assert "2024" in html
        assert "3" in html  # article count
        assert "Inflation / Cpi / Price" in html
        assert "<html" in html.lower()

    def test_html_escapes_user_text(self):
        d = build_digest(
            [{"slug": "x", "title": "T", "date": "2024-01-01", "word_count": 1,
              "cluster_label": "A & B <co>"}],
            [],
            2024,
        )
        html = render_html(d)
        assert "A &amp; B &lt;co&gt;" in html
        assert "<co>" not in html

    def test_markdown_is_plain_text_summary(self):
        d = build_digest(THEME_ARTICLES, PREDICTIONS, 2024)
        md = render_markdown(d)
        assert "2024" in md
        assert "Inflation / Cpi / Price" in md
        assert "<html" not in md.lower()


class TestDefaultYear:
    def test_is_the_latest_complete_calendar_year(self):
        assert default_year(today=datetime.date(2026, 6, 26)) == 2025

    def test_january_first_still_points_at_last_year(self):
        assert default_year(today=datetime.date(2026, 1, 1)) == 2025


class TestRun:
    def test_writes_html_and_returns_payload(self, tmp_path):
        result = run(
            2024,
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            email_dir=tmp_path,
        )
        assert result["year"] == 2024
        assert result["article_count"] == 3
        assert "2024" in result["subject"]
        assert "<html" in result["html_body"].lower()
        written = list(tmp_path.glob("year_in_review_2024.html"))
        assert len(written) == 1
        assert written[0].read_text() == result["html_body"]

    def test_dry_run_writes_nothing(self, tmp_path):
        result = run(
            2024,
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            email_dir=tmp_path,
            write=False,
        )
        assert result["article_count"] == 3
        assert list(tmp_path.glob("*.html")) == []

    def test_defaults_year_when_not_given(self, tmp_path):
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            email_dir=tmp_path,
            write=False,
        )
        assert result["year"] == default_year()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
