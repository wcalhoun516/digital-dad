"""Tests for analysis/anthology.py — the printable "best of" anthology builder.

Roadmap #24 (family). These cover the deterministic, offline pieces: computing the corpus
span, selecting his vindicated "best calls", choosing a signature piece per dominant theme,
assembling the anthology, and rendering the print-ready HTML. No conductor, network, or
LLM is exercised here.
"""

from pathlib import Path

import pytest

from analysis.anthology import (
    best_calls,
    build_anthology,
    corpus_span,
    reasoning_snippet,
    render_html,
    render_markdown,
    render_pdf,
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


class TestReasoningSnippet:
    def test_short_single_sentence_returned_whole(self):
        assert reasoning_snippet("He was right.") == "He was right."

    def test_returns_only_the_first_sentence(self):
        text = "The first point holds. A second, longer elaboration follows here."
        assert reasoning_snippet(text) == "The first point holds."

    def test_long_first_sentence_truncated_at_word_boundary(self):
        words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()
        text = " ".join(words * 6)  # long, no sentence break
        got = reasoning_snippet(text, max_chars=40)
        assert got.endswith("…")
        assert len(got) <= 41
        assert not got.startswith(" ")
        # every token before the ellipsis is a whole word (never split mid-word)
        assert all(tok in words for tok in got[:-1].split())

    def test_empty_or_none_is_blank(self):
        assert reasoning_snippet("") == ""
        assert reasoning_snippet(None) == ""


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

    def test_html_shows_why_a_call_held_up_when_reasoning_present(self):
        preds = [{"claim": "It happened.", "confidence_language": "certain",
                  "llm_verdict": "vindicated", "article_slug": "z",
                  "article_title": "Z", "article_url": "u",
                  "llm_verdict_reasoning": "Events unfolded exactly as forecast. More detail."}]
        html = render_html(build_anthology([], preds))
        assert "Events unfolded exactly as forecast." in html
        # the longer second sentence is trimmed to keep the keepsake tight
        assert "More detail." not in html

    def test_html_omits_why_line_when_no_reasoning(self):
        preds = [{"claim": "It happened.", "confidence_language": "certain",
                  "llm_verdict": "vindicated", "article_slug": "z",
                  "article_title": "Z", "article_url": "u"}]
        html = render_html(build_anthology([], preds))
        assert "class=\"why\"" not in html


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


def _fake_pdf_render(calls):
    """A test seam that records its args and writes a minimal valid PDF byte-signature."""

    def render(html_path, pdf_path):
        calls.append((Path(html_path), Path(pdf_path)))
        Path(pdf_path).write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")

    return render


class TestRenderPdf:
    def test_invokes_seam_and_returns_path(self, tmp_path):
        html = tmp_path / "anthology.html"
        html.write_text("<html><body>hi</body></html>")
        pdf = tmp_path / "anthology.pdf"
        calls = []
        out = render_pdf(html, pdf, render=_fake_pdf_render(calls))
        assert Path(out) == pdf
        assert calls == [(html, pdf)]
        assert pdf.read_bytes().startswith(b"%PDF")

    def test_missing_html_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            render_pdf(tmp_path / "nope.html", tmp_path / "o.pdf", render=lambda h, p: None)

    def test_defaults_to_chromium_seam(self, tmp_path, monkeypatch):
        import analysis.anthology as mod

        html = tmp_path / "anthology.html"
        html.write_text("<html></html>")
        pdf = tmp_path / "anthology.pdf"
        seen = []
        monkeypatch.setattr(mod, "_chromium_render", lambda h, p: seen.append((h, p)))
        render_pdf(html, pdf)  # no render= injected → falls back to the default seam
        assert seen == [(html, pdf)]


class TestRunPdf:
    def test_pdf_true_generates_via_seam(self, tmp_path):
        calls = []
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            out_dir=tmp_path,
            pdf=True,
            pdf_render=_fake_pdf_render(calls),
        )
        pdf_file = tmp_path / "anthology.pdf"
        assert pdf_file.exists()
        assert pdf_file.read_bytes().startswith(b"%PDF")
        assert result["pdf_file"] == str(pdf_file)
        # The seam receives the freshly-written HTML and the target PDF path.
        assert calls == [(tmp_path / "anthology.html", pdf_file)]

    def test_pdf_false_writes_no_pdf(self, tmp_path):
        result = run(theme_articles=THEME_ARTICLES, predictions=PREDICTIONS, out_dir=tmp_path)
        assert result["pdf_file"] is None
        assert not (tmp_path / "anthology.pdf").exists()

    def test_pdf_requires_write(self, tmp_path):
        called = []
        result = run(
            theme_articles=THEME_ARTICLES,
            predictions=PREDICTIONS,
            out_dir=tmp_path,
            write=False,
            pdf=True,
            pdf_render=lambda h, p: called.append(1),
        )
        # No HTML on disk to render from → the seam is never called and nothing is written.
        assert result["pdf_file"] is None
        assert called == []
        assert list(tmp_path.glob("*")) == []


class TestMainPdfFlag:
    def test_pdf_flag_passes_through(self, tmp_path, monkeypatch, capsys):
        import analysis.anthology as mod

        seen = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return {
                "markdown": "x",
                "html_file": str(tmp_path / "a.html"),
                "json_file": str(tmp_path / "a.json"),
                "pdf_file": str(tmp_path / "a.pdf"),
            }

        monkeypatch.setattr(mod, "run", fake_run)
        rc = mod.main(["--pdf"])
        assert rc == 0
        assert seen.get("pdf") is True
        assert "a.pdf" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
