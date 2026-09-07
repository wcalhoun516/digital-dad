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
    verdict_tally,
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

# Deliberately ordered so conviction and verdict *disagree*: ranked by conviction alone the
# certain-but-wrong call leads, and the hedged-but-right one comes last. Each claim gets its
# own article_slug so the max_per_article cap doesn't mask the ordering under test.
ADJUDICATED = [
    {"claim": "Certain but wrong.", "confidence_language": "certain",
     "article_date": "2024-03-01", "article_slug": "p1", "article_title": "One",
     "llm_verdict": "wrong"},
    {"claim": "Certain but unfalsifiable.", "confidence_language": "certain",
     "article_date": "2024-03-02", "article_slug": "p2", "article_title": "Two",
     "llm_verdict": "unfalsifiable"},
    {"claim": "Certain but unjudged.", "confidence_language": "certain",
     "article_date": "2024-03-03", "article_slug": "p3", "article_title": "Three"},
    {"claim": "Confident and mixed.", "confidence_language": "confident",
     "article_date": "2024-03-04", "article_slug": "p4", "article_title": "Four",
     "llm_verdict": "mixed"},
    {"claim": "Hedged but right.", "confidence_language": "hedged",
     "article_date": "2024-03-05", "article_slug": "p5", "article_title": "Five",
     "llm_verdict": "vindicated"},
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

    def test_caps_predictions_per_article_by_default(self):
        # One article hogs three high-conviction claims; the digest should still span
        # multiple pieces rather than showing the same article three times.
        hoggy = [
            {"claim": "Call one.", "confidence_language": "certain",
             "article_date": "2024-01-01", "article_slug": "big-piece",
             "article_title": "Big Piece"},
            {"claim": "Call two.", "confidence_language": "certain",
             "article_date": "2024-01-01", "article_slug": "big-piece",
             "article_title": "Big Piece"},
            {"claim": "Call three.", "confidence_language": "certain",
             "article_date": "2024-01-01", "article_slug": "big-piece",
             "article_title": "Big Piece"},
            {"claim": "Other call.", "confidence_language": "confident",
             "article_date": "2024-02-02", "article_slug": "other-piece",
             "article_title": "Other Piece"},
        ]
        got = notable_predictions(hoggy, 2024)
        slugs = [p["article_slug"] for p in got]
        assert slugs.count("big-piece") == 1
        assert "other-piece" in slugs

    def test_a_vindicated_call_outranks_a_more_confident_wrong_one(self):
        # The keepsake leads with calls that came good, not merely calls stated loudly.
        got = notable_predictions(ADJUDICATED, 2024)
        assert [p["claim"] for p in got] == [
            "Hedged but right.",
            "Confident and mixed.",
            "Certain but wrong.",
            "Certain but unfalsifiable.",
            "Certain but unjudged.",
        ]

    def test_unfalsifiable_and_unjudged_claims_sink_below_real_calls(self):
        got = notable_predictions(ADJUDICATED, 2024, limit=3)
        claims = [p["claim"] for p in got]
        assert "Certain but unfalsifiable." not in claims
        assert "Certain but unjudged." not in claims

    def test_conviction_still_orders_within_a_verdict_tier(self):
        same_verdict = [
            {"claim": "Hedged.", "confidence_language": "hedged", "article_date": "2024-01-01",
             "article_slug": "h", "llm_verdict": "vindicated"},
            {"claim": "Certain.", "confidence_language": "certain", "article_date": "2024-01-02",
             "article_slug": "c", "llm_verdict": "vindicated"},
        ]
        got = notable_predictions(same_verdict, 2024)
        assert [p["claim"] for p in got] == ["Certain.", "Hedged."]

    def test_a_human_ruling_outranks_the_advisory_llm_verdict(self):
        # adjudicate.effective_verdict precedence: human_verdict > evidence_verdict > llm_verdict.
        overridden = [
            {"claim": "LLM says wrong, human says right.", "confidence_language": "hedged",
             "article_date": "2024-01-01", "article_slug": "a",
             "llm_verdict": "wrong", "human_verdict": "vindicated"},
            {"claim": "Plainly mixed.", "confidence_language": "certain",
             "article_date": "2024-01-02", "article_slug": "b", "llm_verdict": "mixed"},
        ]
        got = notable_predictions(overridden, 2024)
        assert got[0]["claim"] == "LLM says wrong, human says right."

    def test_max_per_article_is_configurable(self):
        hoggy = [
            {"claim": "Call one.", "confidence_language": "certain",
             "article_date": "2024-01-01", "article_slug": "big-piece"},
            {"claim": "Call two.", "confidence_language": "certain",
             "article_date": "2024-01-01", "article_slug": "big-piece"},
        ]
        got = notable_predictions(hoggy, 2024, max_per_article=2)
        assert len(got) == 2


class TestVerdictLabels:
    def test_html_labels_each_call_with_its_verdict(self):
        d = build_digest([], ADJUDICATED, 2024, predictions_n=6)
        html = render_html(d)
        assert "Vindicated" in html
        assert "Wrong" in html

    def test_html_does_not_present_a_wrong_call_as_merely_confident(self):
        # The bug: a call judged wrong showed only its confidence label ("Certain").
        d = build_digest([], [ADJUDICATED[0]], 2024)
        html = render_html(d)
        assert "Certain but wrong." in html
        assert "Wrong" in html

    def test_unjudged_calls_read_as_not_yet_judged_rather_than_pending(self):
        d = build_digest([], [ADJUDICATED[2]], 2024)
        html = render_html(d)
        assert "Not yet judged" in html

    def test_markdown_labels_each_call_with_its_verdict(self):
        d = build_digest([], ADJUDICATED, 2024, predictions_n=6)
        md = render_markdown(d)
        assert "Vindicated" in md
        assert "Wrong" in md


class TestVerdictTally:
    def test_counts_only_adjudicated_calls_for_the_year(self):
        assert verdict_tally(ADJUDICATED, 2024) == {
            "vindicated": 1, "mixed": 1, "wrong": 1, "total": 3
        }

    def test_ignores_other_years(self):
        assert verdict_tally(ADJUDICATED, 2023) == {
            "vindicated": 0, "mixed": 0, "wrong": 0, "total": 0
        }

    def test_counts_every_call_not_just_the_ones_shown(self):
        # The scoreboard is the year's whole record; the digest only *shows* a handful.
        many = [
            dict(p, claim=f"c{i}", article_slug=f"s{i}", article_date="2024-01-01")
            for i, p in enumerate([ADJUDICATED[0]] * 9)
        ]
        assert verdict_tally(many, 2024)["wrong"] == 9

    def test_a_human_ruling_wins_in_the_tally_too(self):
        overridden = [{"article_date": "2024-01-01", "llm_verdict": "wrong",
                       "human_verdict": "vindicated"}]
        assert verdict_tally(overridden, 2024)["vindicated"] == 1

    def test_digest_carries_the_tally(self):
        d = build_digest([], ADJUDICATED, 2024)
        assert d["verdict_tally"]["total"] == 3

    def test_html_states_the_years_record(self):
        d = build_digest([], ADJUDICATED, 2024)
        html = render_html(d)
        assert "1 came good" in html

    def test_markdown_states_the_years_record(self):
        md = render_markdown(build_digest([], ADJUDICATED, 2024))
        assert "1 came good" in md

    def test_no_scoreboard_when_nothing_was_adjudicated(self):
        unjudged = [{"claim": "x", "article_date": "2024-01-01", "article_slug": "u"}]
        html = render_html(build_digest([], unjudged, 2024))
        assert "came good" not in html


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
