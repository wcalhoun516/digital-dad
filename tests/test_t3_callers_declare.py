"""Every paid-T3 caller declares what it is sending (roadmap #38).

The guard in ``_call`` fails closed, so a caller that declares nothing simply stops working
at tier 3. These tests pin down what each of the four declares, because a declaration that
is *wrong* is worse than none: it would wave private material through.
"""

import pytest

from analysis import predictions, rag_eval, verdict_backfill, voice_eval

MANIFEST = {
    "articles": [
        {"slug": "public-column", "url": "http://forbes.com/x", "file": "raw/public-column.json"},
        {"slug": "a-letter", "provenance": {"source_id": "a-letter", "privacy": "private"}},
    ]
}


@pytest.fixture
def recorded_calls(monkeypatch):
    """Capture every ``_call`` the module under test makes, without a conductor."""
    calls = []

    def fake_call(client, prompt, max_tokens=4096, tier=2, sources=None):
        calls.append({"tier": tier, "sources": sources, "prompt": prompt})
        return "[]"

    monkeypatch.setattr(predictions, "_call", fake_call)
    monkeypatch.setattr(predictions, "_get_client", lambda: object())
    return calls


@pytest.fixture
def fixed_manifest(monkeypatch):
    monkeypatch.setattr("analysis.utils.load_manifest", lambda: MANIFEST)


class TestPredictions:
    def test_extraction_declares_the_article_it_is_reading(self, recorded_calls):
        article = {"slug": "public-column", "title": "T", "date": "2020-01-01", "body": "b"}
        predictions._extract_predictions(object(), article, tier=3)
        assert recorded_calls[0]["sources"] == [article]

    def test_verdicts_declare_only_the_articles_in_the_batch(self, recorded_calls, fixed_manifest):
        """One private letter elsewhere in the corpus must not block a public batch."""
        batch = [{"claim": "c", "article_slug": "public-column", "article_date": "2020-01-01"}]
        predictions._run_verdicts(object(), batch, tier=3)
        declared = {b["source_id"] for b in recorded_calls[0]["sources"]}
        assert declared == {"public-column"}


class TestRagEval:
    def test_generation_declares_the_retrieved_articles(self, recorded_calls, fixed_manifest):
        generate = rag_eval._live_generate(tier=3)
        generate("q?", [{"slug": "public-column", "title": "T", "snippet": "s"}])
        assert {b["source_id"] for b in recorded_calls[0]["sources"]} == {"public-column"}

    def test_a_retrieved_private_document_is_declared_as_such(self, recorded_calls, fixed_manifest):
        generate = rag_eval._live_generate(tier=3)
        generate("q?", [{"slug": "a-letter", "title": "T", "snippet": "s"}])
        assert recorded_calls[0]["sources"][0]["privacy"] == "private"

    def test_judging_declares_the_retrieved_articles(self, recorded_calls, fixed_manifest):
        judge = rag_eval._live_judge(tier=3)
        judge("q?", "an answer", [{"slug": "public-column", "title": "T", "snippet": "s"}])
        assert {b["source_id"] for b in recorded_calls[0]["sources"]} == {"public-column"}


class TestWholeCorpusCallers:
    """Two callers quote passages they cannot attribute to a slug, so they declare the lot."""

    def test_voice_judge_declares_the_whole_corpus(self, recorded_calls, fixed_manifest):
        judge = voice_eval._live_judge(tier=3)
        judge("prompt", {"a": "passage one", "b": "passage two"})
        declared = {b["source_id"] for b in recorded_calls[0]["sources"]}
        assert declared == {"public-column", "a-letter"}

    def test_verdict_backfill_declares_the_whole_corpus(self, recorded_calls, fixed_manifest):
        chat = verdict_backfill._conductor_chat(tier=3)
        chat("some prompt")
        declared = {b["source_id"] for b in recorded_calls[0]["sources"]}
        assert declared == {"public-column", "a-letter"}


class TestNoCallerDeclaresNothing:
    """A regression net: a future caller that forgets is caught here, not in production."""

    def test_no_remote_call_site_passes_sources_none(self, recorded_calls, fixed_manifest):
        article = {"slug": "public-column", "title": "T", "date": "2020-01-01", "body": "b"}
        predictions._extract_predictions(object(), article, tier=3)
        rag_eval._live_generate(tier=3)("q?", [{"slug": "public-column", "snippet": "s"}])
        voice_eval._live_judge(tier=3)("p", {"a": "x"})
        verdict_backfill._conductor_chat(tier=3)("p")
        assert all(call["sources"] is not None for call in recorded_calls)
        assert len(recorded_calls) == 4
