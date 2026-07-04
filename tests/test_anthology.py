"""Tests for analysis/anthology.py — the printable "best of" anthology builder.

Roadmap #24 (family). These cover the deterministic, offline pieces: computing the corpus
span, selecting his vindicated "best calls", choosing a signature piece per dominant theme,
assembling the anthology, and rendering the print-ready HTML. No conductor, network, or
LLM is exercised here.
"""

import pytest

from analysis.anthology import (
    best_calls,
    build_anthology,
    corpus_span,
    render_html,
    render_markdown,
    run,
    signature_pieces,
)

THEME_ARTICLES = [
    {"slug": "a", "title": "Inflation Is Back", "date": "2024-02-01",
     "word_count": 1200, "cluster_label": "Inflation / Cpi / Price",
     "url": "https://forbes.com/a"},
    {"slug": "b", "title": "The Fed Blinks", "date": "2021-06-15",
     "word_count": 900, "cluster_label": "Fed / Financial / Wireless",
     "url": "https://forbes.com/b"},
    {"slug": "c", "title": "CPI Again", "date": "2024-09-09",
     "word_count": 1500, "cluster_label": "Inflation / Cpi / Price",
     "url": "https://forbes.com/c"},
    {"slug": "d", "title": "Rates Rising", "date": "2022-12-31",
     "word_count": 800, "cluster_label": "Fed / Financial / Wireless",
     "url": "https://forbes.com/d"},
    {"slug": "e", "title": "No Date Listing", "date": "",
     "word_count": 5000, "cluster_label": "Fed / Financial / Wireless",
     "url": "https://forbes.com/e"},
]

PREDICTIONS = [
    {"claim": "Inflation will stay above 3% through 2024.", "topic": "inflation",
     "confidence_language": "confident", "llm_verdict": "vindicated",
     "article_date": "2024-02-01", "article_slug": "a",
     "article_title": "Inflation Is Back", "article_url": "https://forbes.com/a"},
    {"claim": "The Fed will not cut before September.", "topic": "Fed policy",
     "confidence_language": "certain", "llm_verdict": "vindicated",
     "article_date": "2021-06-15", "article_slug": "b",
     "article_title": "The Fed Blinks", "article_url": "https://forbes.com/b"},
    {"claim": "A hedged but correct maybe.", "topic": "markets",
     "confidence_language": "hedged", "llm_verdict": "vindicated",
     "article_date": "2024-09-09", "article_slug": "c",
     "article_title": "CPI Again", "article_url": "https://forbes.com/c"},
    {"claim": "This one was wrong.", "topic": "oil",
     "confidence_language": "certain", "llm_verdict": "wrong",
     "article_date": "2022-05-05", "article_slug": "d",
     "article_title": "Rates Rising", "article_url": "https://forbes.com/d"},
    {"claim": "Too early to tell.", "topic": "crypto",
     "confidence_language": "confident", "llm_verdict": "pending",
     "article_date": "2024-01-01", "article_slug": "a",
     "article_title": "Inflation Is Back", "article_url": "https://forbes.com/a"},
]


class TestCorpusSpan:
    def test_reports_first_last_date_and_count_of_dated_articles(self):
        span = corpus_span(THEME_ARTICLES)
        assert span["first_date"] == "2021-06-15"
        assert span["last_date"] == "2024-09-09"
        assert span["count"] == 4  # the undated author-listing page is excluded

    def test_empty_corpus_is_safe(self):
        span = corpus_span([])
        assert span["count"] == 0
        assert span["first_date"] is None
        assert span["last_date"] is None


class TestBestCalls:
    def test_only_vindicated_calls_ranked_by_conviction(self):
        got = best_calls(PREDICTIONS)
        # wrong/pending dropped; certain > confident > hedged among the vindicated.
        assert [p["claim"] for p in got] == [
            "The Fed will not cut before September.",
            "Inflation will stay above 3% through 2024.",
            "A hedged but correct maybe.",
        ]

    def test_respects_limit(self):
        got = best_calls(PREDICTIONS, limit=1)
        assert len(got) == 1
        assert got[0]["confidence_language"] == "certain"

    def test_dedupes_identical_claims(self):
        dupes = PREDICTIONS + [dict(PREDICTIONS[0])]
        got = best_calls(dupes)
        claims = [p["claim"] for p in got]
        assert claims.count("Inflation will stay above 3% through 2024.") == 1

    def test_caps_calls_per_article_by_default(self):
        hoggy = [
            {"claim": "Call one.", "confidence_language": "certain",
             "llm_verdict": "vindicated", "article_slug": "big"},
            {"claim": "Call two.", "confidence_language": "certain",
             "llm_verdict": "vindicated", "article_slug": "big"},
            {"claim": "Other.", "confidence_language": "confident",
             "llm_verdict": "vindicated", "article_slug": "other"},
        ]
        got = best_calls(hoggy)
        slugs = [p["article_slug"] for p in got]
        assert slugs.count("big") == 1
        assert "other" in slugs

    def test_empty_when_nothing_vindicated(self):
        losers = [{"claim": "x", "llm_verdict": "wrong",
                   "confidence_language": "certain", "article_slug": "z"}]
        assert best_calls(losers) == []


class TestSignaturePieces:
    def test_one_representative_article_per_top_theme(self):
        got = signature_pieces(THEME_ARTICLES)
        # Both themes have 2 dated articles → tie broken alphabetically by label.
        assert [s["theme"] for s in got] == [
            "Fed / Financial / Wireless",
            "Inflation / Cpi / Price",
        ]
        # Representative = highest word_count within the theme (among dated articles).
        assert got[0]["article"]["slug"] == "b"  # 900 > 800
        assert got[1]["article"]["slug"] == "c"  # 1500 > 1200

    def test_excludes_undated_articles_as_candidates(self):
        # The undated 5000-word listing page must never be a signature piece even though
        # it would otherwise dominate its theme by word count.
        got = signature_pieces(THEME_ARTICLES)
        chosen = {s["article"]["slug"] for s in got}
        assert "e" not in chosen

    def test_respects_top_n(self):
        got = signature_pieces(THEME_ARTICLES, top_n=1)
        assert len(got) == 1

    def test_empty_input(self):
        assert signature_pieces([]) == []


class TestBuildAnthology:
    def test_assembles_the_full_anthology(self):
        a = build_anthology(THEME_ARTICLES, PREDICTIONS)
        assert a["span"]["count"] == 4
        assert a["best_calls"][0]["confidence_language"] == "certain"
        assert a["signature_pieces"][0]["theme"] == "Fed / Financial / Wireless"

    def test_empty_corpus_is_safe(self):
        a = build_anthology([], [])
        assert a["span"]["count"] == 0
        assert a["best_calls"] == []
        assert a["signature_pieces"] == []


class TestRenderers:
    def test_html_is_print_ready_and_includes_content(self):
        a = build_anthology(THEME_ARTICLES, PREDICTIONS)
        html = render_html(a)
        assert "<html" in html.lower()
        assert "@media print" in html  # print-optimized stylesheet
        assert "The Fed will not cut before September." in html
        assert "Inflation / Cpi / Price" in html

    def test_html_escapes_user_text(self):
        a = build_anthology(
            [{"slug": "x", "title": "T & <co>", "date": "2024-01-01",
              "word_count": 1, "cluster_label": "A & B <co>", "url": "u"}],
            [],
        )
        html = render_html(a)
        assert "A &amp; B &lt;co&gt;" in html
        assert "<co>" not in html

    def test_markdown_is_plain_text_summary(self):
        a = build_anthology(THEME_ARTICLES, PREDICTIONS)
        md = render_markdown(a)
        assert "<html" not in md.lower()
        assert "The Fed will not cut before September." in md


class TestRun:
    def test_writes_json_and_html_and_returns_payload(self, tmp_path):
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            out_dir=tmp_path,
        )
        assert "<html" in result["html_body"].lower()
        json_file = tmp_path / "anthology.json"
        html_file = tmp_path / "anthology.html"
        assert json_file.exists()
        assert html_file.exists()
        assert html_file.read_text() == result["html_body"]

    def test_dry_run_writes_nothing(self, tmp_path):
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            out_dir=tmp_path,
            write=False,
        )
        assert result["anthology"]["span"]["count"] == 4
        assert list(tmp_path.glob("*")) == []

    def test_limit_caps_best_calls(self, tmp_path):
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            out_dir=tmp_path,
            write=False,
            calls_limit=1,
        )
        assert len(result["anthology"]["best_calls"]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
