"""Tests for analysis/verdict_backfill.py — the evidence-augmented verdict pass.

Plan 0004 step 1. Exercises pure logic only: prompt assembly, response parsing, the
per-prediction writeback, the resume predicate, and the resumable/incremental run loop.
The compute-heavy seams (web search + T3 chat) are injected as fakes, so no conductor
and no network are touched here.
"""

import json

from analysis.verdict_backfill import (
    VALID_CONFIDENCE,
    VALID_VERDICTS,
    augment_prediction,
    build_prompt,
    format_evidence,
    needs_backfill,
    normalize_sources,
    parse_verdict,
    run_backfill,
)


class TestFormatEvidence:
    def test_empty_sources_is_marked(self):
        assert "no external evidence" in format_evidence([]).lower()

    def test_numbers_and_includes_title_url_snippet(self):
        out = format_evidence(
            [{"title": "Fed holds", "url": "https://x/1", "snippet": "rates unchanged"}]
        )
        assert "[1]" in out
        assert "Fed holds" in out
        assert "https://x/1" in out
        assert "rates unchanged" in out


class TestBuildPrompt:
    def test_includes_claim_date_and_evidence(self):
        pred = {
            "claim": "Bitcoin will hit 100k by 2025",
            "prediction_date": "2021-04-01",
            "topic": "Bitcoin",
        }
        sources = [{"title": "BTC price", "url": "https://x", "snippet": "it did"}]
        prompt = build_prompt(pred, sources, current_date="2026-06-05")
        assert "Bitcoin will hit 100k by 2025" in prompt
        assert "2021-04-01" in prompt
        assert "2026-06-05" in prompt
        assert "BTC price" in prompt

    def test_empty_evidence_still_builds(self):
        prompt = build_prompt({"claim": "c", "prediction_date": "2020-01-01"}, [],
                              current_date="2026-06-05")
        assert "c" in prompt
        assert "no external evidence" in prompt.lower()


class TestParseVerdict:
    def test_parses_clean_object(self):
        text = json.dumps({
            "verdict": "vindicated",
            "reasoning": "it happened",
            "confidence": "high",
            "sources": ["https://a", "https://b"],
        })
        out = parse_verdict(text)
        assert out["verdict"] == "vindicated"
        assert out["reasoning"] == "it happened"
        assert out["confidence"] == "high"
        assert out["sources"] == ["https://a", "https://b"]

    def test_tolerates_surrounding_prose_and_fences(self):
        text = 'Here is my ruling:\n```json\n{"verdict": "wrong", "reasoning": "no"}\n```\nDone.'
        out = parse_verdict(text)
        assert out["verdict"] == "wrong"
        assert out["reasoning"] == "no"

    def test_returns_none_on_unparseable(self):
        assert parse_verdict("the model said nothing useful") is None

    def test_returns_none_on_invalid_verdict(self):
        assert parse_verdict('{"verdict": "definitely-true"}') is None

    def test_defaults_confidence_to_low_when_missing_or_invalid(self):
        assert parse_verdict('{"verdict": "mixed"}')["confidence"] == "low"
        assert parse_verdict('{"verdict": "mixed", "confidence": "wild"}')["confidence"] == "low"

    def test_accepts_verdict_reasoning_alias(self):
        out = parse_verdict('{"verdict": "mixed", "verdict_reasoning": "partly"}')
        assert out["reasoning"] == "partly"

    def test_non_list_sources_coerced_to_empty(self):
        assert parse_verdict('{"verdict": "mixed", "sources": "oops"}')["sources"] == []


class TestNormalizeSources:
    def test_dicts_keep_title_and_url_only(self):
        out = normalize_sources([{"title": "t", "url": "u", "snippet": "drop me"}])
        assert out == [{"title": "t", "url": "u"}]

    def test_strings_become_url_only(self):
        assert normalize_sources(["https://x"]) == [{"title": "", "url": "https://x"}]

    def test_skips_junk(self):
        assert normalize_sources([42, None]) == []


class TestAugmentPrediction:
    def _chat(self, payload):
        return lambda prompt: json.dumps(payload)

    def test_writes_evidence_fields(self):
        pred = {"claim": "c", "prediction_date": "2020-01-01"}
        chat = self._chat({
            "verdict": "vindicated", "reasoning": "yep", "confidence": "high",
            "sources": ["https://a"],
        })
        sources = [{"title": "T", "url": "https://a", "snippet": "s"}]
        out = augment_prediction(pred, sources, chat,
                                 current_date="2026-06-05", now="2026-06-05T00:00:00Z")
        assert out["evidence_verdict"] == "vindicated"
        assert out["evidence_verdict_reasoning"] == "yep"
        assert out["evidence_verdict_confidence"] == "high"
        assert out["evidence_sources"] == [{"title": "T", "url": "https://a"}]
        assert out["evidence_verdict_at"] == "2026-06-05T00:00:00Z"

    def test_returns_none_and_writes_nothing_on_bad_response(self):
        pred = {"claim": "c", "prediction_date": "2020-01-01"}
        out = augment_prediction(pred, [], lambda p: "garbage",
                                 current_date="2026-06-05")
        assert out is None
        assert "evidence_verdict" not in pred

    def test_does_not_touch_advisory_llm_or_human_fields(self):
        pred = {"claim": "c", "prediction_date": "2020-01-01",
                "llm_verdict": "wrong", "human_verdict": "mixed"}
        augment_prediction(pred, [], self._chat({"verdict": "vindicated"}),
                           current_date="2026-06-05", now="2026-06-05T00:00:00Z")
        assert pred["llm_verdict"] == "wrong"
        assert pred["human_verdict"] == "mixed"


class TestNeedsBackfill:
    def test_true_when_no_evidence_verdict(self):
        assert needs_backfill({"claim": "c"}) is True

    def test_false_when_evidence_verdict_present(self):
        assert needs_backfill({"claim": "c", "evidence_verdict": "wrong"}) is False

    def test_empty_evidence_verdict_still_needs_backfill(self):
        assert needs_backfill({"claim": "c", "evidence_verdict": ""}) is True


class TestRunBackfill:
    def _chat(self, prompt):
        return json.dumps({"verdict": "vindicated", "reasoning": "r", "confidence": "low"})

    def test_only_processes_predictions_needing_backfill(self):
        preds = [
            {"claim": "a"},
            {"claim": "b", "evidence_verdict": "wrong"},  # already done
            {"claim": "c"},
        ]
        summary = run_backfill(preds, gather_evidence=lambda p: [], chat=self._chat)
        assert summary["targets"] == 2
        assert summary["processed"] == 2
        assert preds[0]["evidence_verdict"] == "vindicated"
        assert preds[1]["evidence_verdict"] == "wrong"  # untouched

    def test_limit_caps_targets(self):
        preds = [{"claim": str(i)} for i in range(5)]
        summary = run_backfill(preds, gather_evidence=lambda p: [], chat=self._chat, limit=2)
        assert summary["targets"] == 2
        assert summary["processed"] == 2
        assert needs_backfill(preds[2])  # 3rd left untouched

    def test_checkpoints_every_n_plus_final(self):
        preds = [{"claim": str(i)} for i in range(25)]
        calls = {"n": 0}

        def save():
            calls["n"] += 1

        run_backfill(preds, gather_evidence=lambda p: [], chat=self._chat,
                     save=save, save_every=10)
        # saves at 10, 20, and a final flush = 3
        assert calls["n"] == 3

    def test_no_final_save_when_nothing_processed(self):
        preds = [{"claim": "a", "evidence_verdict": "wrong"}]
        calls = {"n": 0}
        run_backfill(preds, gather_evidence=lambda p: [], chat=self._chat,
                     save=lambda: calls.__setitem__("n", calls["n"] + 1), save_every=10)
        assert calls["n"] == 0

    def test_bad_response_counts_as_failed_not_processed(self):
        preds = [{"claim": "a"}]
        summary = run_backfill(preds, gather_evidence=lambda p: [],
                               chat=lambda prompt: "no json here")
        assert summary["processed"] == 0
        assert summary["failed"] == 1

    def test_evidence_failure_falls_back_to_empty_and_still_verdicts(self):
        preds = [{"claim": "a"}]

        def boom(p):
            raise RuntimeError("search down")

        summary = run_backfill(preds, gather_evidence=boom, chat=self._chat)
        assert summary["processed"] == 1
        assert preds[0]["evidence_verdict"] == "vindicated"


class TestConstants:
    def test_verdict_and_confidence_vocab(self):
        assert "vindicated" in VALID_VERDICTS
        assert set(VALID_CONFIDENCE) == {"low", "medium", "high"}
