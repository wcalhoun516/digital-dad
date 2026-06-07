"""Tests for analysis/adjudicate.py — the human adjudication layer for Track Record.

Covers plan 0004 steps 2+3: status precedence (human verdict wins over the advisory
LLM verdict) and the writeback that records a family member's decision. Pure logic only
— no conductor, no network, no interactive prompts are exercised here.
"""

import json

from analysis.adjudicate import (
    VALID_VERDICTS,
    adjudication_summary,
    apply_adjudication,
    calibration_report,
    conviction_boards,
    effective_source,
    effective_verdict,
    iter_unadjudicated,
    load_predictions,
    save_predictions,
)


class TestEffectiveVerdict:
    def test_human_verdict_wins_over_llm_and_status(self):
        p = {"human_verdict": "wrong", "llm_verdict": "vindicated", "status": "pending"}
        assert effective_verdict(p) == "wrong"

    def test_falls_back_to_llm_when_no_human(self):
        p = {"llm_verdict": "vindicated", "status": "pending"}
        assert effective_verdict(p) == "vindicated"

    def test_evidence_verdict_wins_over_llm_but_not_human(self):
        p = {"human_verdict": "wrong", "evidence_verdict": "mixed", "llm_verdict": "vindicated"}
        assert effective_verdict(p) == "wrong"
        p2 = {"evidence_verdict": "mixed", "llm_verdict": "vindicated", "status": "pending"}
        assert effective_verdict(p2) == "mixed"

    def test_falls_back_to_status_when_no_human_or_llm(self):
        p = {"status": "unfalsifiable"}
        assert effective_verdict(p) == "unfalsifiable"

    def test_defaults_to_pending_when_nothing_set(self):
        assert effective_verdict({}) == "pending"

    def test_ignores_empty_string_verdicts(self):
        p = {"human_verdict": "", "llm_verdict": "mixed"}
        assert effective_verdict(p) == "mixed"


class TestEffectiveSource:
    def test_human_when_human_verdict_present(self):
        assert effective_source({"human_verdict": "wrong", "llm_verdict": "mixed"}) == "human"

    def test_llm_when_only_llm_verdict(self):
        assert effective_source({"llm_verdict": "mixed"}) == "llm"

    def test_evidence_when_evidence_present_without_human(self):
        assert effective_source({"evidence_verdict": "mixed", "llm_verdict": "wrong"}) == "evidence"

    def test_human_still_wins_over_evidence(self):
        assert effective_source({"human_verdict": "wrong", "evidence_verdict": "mixed"}) == "human"

    def test_pending_when_neither(self):
        assert effective_source({"status": "pending"}) == "pending"


class TestApplyAdjudication:
    def test_records_verdict_note_source_and_status(self):
        p = {"claim": "X will happen", "llm_verdict": "vindicated", "status": "pending"}
        out = apply_adjudication(p, "wrong", note="Did not happen.", now="2026-06-04T12:00:00Z")
        assert out["human_verdict"] == "wrong"
        assert out["human_verdict_note"] == "Did not happen."
        assert out["human_verdict_at"] == "2026-06-04T12:00:00Z"
        assert out["verdict_source"] == "human"
        assert out["status"] == "wrong"

    def test_preserves_advisory_llm_fields(self):
        p = {"claim": "c", "llm_verdict": "vindicated", "llm_verdict_reasoning": "because"}
        out = apply_adjudication(p, "mixed", now="2026-06-04T00:00:00Z")
        assert out["llm_verdict"] == "vindicated"
        assert out["llm_verdict_reasoning"] == "because"

    def test_note_defaults_to_empty_string(self):
        out = apply_adjudication({"claim": "c"}, "vindicated", now="2026-06-04T00:00:00Z")
        assert out["human_verdict_note"] == ""

    def test_rejects_invalid_verdict(self):
        try:
            apply_adjudication({"claim": "c"}, "definitely-true", now="2026-06-04T00:00:00Z")
        except ValueError as exc:
            assert "definitely-true" in str(exc)
        else:
            raise AssertionError("expected ValueError for invalid verdict")

    def test_re_adjudication_overrides_prior_human_verdict(self):
        p = {"claim": "c", "human_verdict": "wrong", "status": "wrong"}
        out = apply_adjudication(p, "mixed", note="on reflection", now="2026-06-05T00:00:00Z")
        assert out["human_verdict"] == "mixed"
        assert out["status"] == "mixed"
        assert out["human_verdict_note"] == "on reflection"

    def test_all_valid_verdicts_accepted(self):
        for v in VALID_VERDICTS:
            out = apply_adjudication({"claim": "c"}, v, now="2026-06-04T00:00:00Z")
            assert out["human_verdict"] == v


class TestIterUnadjudicated:
    def test_yields_only_predictions_without_human_verdict(self):
        preds = [
            {"claim": "a"},
            {"claim": "b", "human_verdict": "wrong"},
            {"claim": "c", "human_verdict": ""},
        ]
        out = [p["claim"] for p in iter_unadjudicated(preds)]
        assert out == ["a", "c"]

    def test_empty_when_all_adjudicated(self):
        preds = [{"claim": "a", "human_verdict": "mixed"}]
        assert list(iter_unadjudicated(preds)) == []


class TestAdjudicationSummary:
    def test_counts_total_adjudicated_and_effective_verdicts(self):
        preds = [
            {"claim": "a", "llm_verdict": "vindicated"},
            {"claim": "b", "llm_verdict": "wrong", "human_verdict": "mixed", "status": "mixed"},
            {"claim": "c", "status": "pending"},
        ]
        summary = adjudication_summary(preds)
        assert summary["total"] == 3
        assert summary["adjudicated"] == 1
        assert summary["pending_adjudication"] == 2
        assert summary["by_verdict"]["vindicated"] == 1
        assert summary["by_verdict"]["mixed"] == 1
        assert summary["by_verdict"]["pending"] == 1


class TestCalibrationReport:
    def _preds(self):
        return [
            {"claim": "1", "confidence_language": "certain", "llm_verdict": "vindicated"},
            {"claim": "2", "confidence_language": "certain", "llm_verdict": "wrong"},
            {"claim": "3", "confidence_language": "certain", "llm_verdict": "mixed"},
            {"claim": "4", "confidence_language": "hedged", "llm_verdict": "vindicated"},
            {"claim": "5", "confidence_language": "hedged", "llm_verdict": "pending"},
            {"claim": "6", "confidence_language": "hedged", "llm_verdict": "unfalsifiable"},
        ]

    def test_accuracy_uses_vindicated_plus_half_mixed_over_resolved(self):
        report = calibration_report(self._preds())
        # certain: vindicated=1, wrong=1, mixed=1 -> resolved=3, acc=(1+0.5)/3=0.5
        certain = report["by_confidence"]["certain"]
        assert certain["resolved"] == 3
        assert certain["vindicated"] == 1
        assert certain["wrong"] == 1
        assert certain["mixed"] == 1
        assert certain["accuracy"] == 0.5

    def test_excludes_pending_and_unfalsifiable_from_resolved(self):
        report = calibration_report(self._preds())
        # hedged: vindicated=1 resolved, pending+unfalsifiable excluded
        hedged = report["by_confidence"]["hedged"]
        assert hedged["resolved"] == 1
        assert hedged["accuracy"] == 1.0

    def test_accuracy_none_when_nothing_resolved(self):
        report = calibration_report(
            [{"claim": "x", "confidence_language": "confident", "llm_verdict": "pending"}]
        )
        assert report["by_confidence"]["confident"]["accuracy"] is None

    def test_human_verdict_overrides_llm_in_calibration(self):
        preds = [
            {"claim": "1", "confidence_language": "certain",
             "llm_verdict": "vindicated", "human_verdict": "wrong"},
        ]
        certain = calibration_report(preds)["by_confidence"]["certain"]
        assert certain["wrong"] == 1
        assert certain["vindicated"] == 0
        assert certain["accuracy"] == 0.0


class TestConvictionBoards:
    def test_high_conviction_hits_and_misses_only(self):
        preds = [
            {"claim": "bold-right", "confidence_language": "certain", "llm_verdict": "vindicated"},
            {"claim": "bold-wrong", "confidence_language": "confident", "llm_verdict": "wrong"},
            {"claim": "hedged-wrong", "confidence_language": "hedged", "llm_verdict": "wrong"},
            {"claim": "hedged-right", "confidence_language": "hedged", "llm_verdict": "vindicated"},
        ]
        boards = conviction_boards(preds)
        right_claims = [p["claim"] for p in boards["most_right"]]
        wrong_claims = [p["claim"] for p in boards["most_wrong"]]
        assert right_claims == ["bold-right"]
        assert wrong_claims == ["bold-wrong"]

    def test_limit_caps_each_board(self):
        preds = [
            {"claim": f"w{i}", "confidence_language": "certain", "llm_verdict": "wrong"}
            for i in range(10)
        ]
        boards = conviction_boards(preds, limit=3)
        assert len(boards["most_wrong"]) == 3


class TestLoadSavePredictions:
    def test_round_trip_preserves_predictions_and_top_level_keys(self, tmp_path):
        path = tmp_path / "predictions.json"
        data = {
            "generated": "2026-06-04T00:00:00Z",
            "num_predictions": 2,
            "predictions": [{"claim": "a"}, {"claim": "b"}],
        }
        path.write_text(json.dumps(data))

        loaded = load_predictions(path)
        assert loaded["num_predictions"] == 2
        assert [p["claim"] for p in loaded["predictions"]] == ["a", "b"]

        loaded["predictions"][0]["human_verdict"] = "wrong"
        save_predictions(path, loaded)

        reloaded = json.loads(path.read_text())
        assert reloaded["predictions"][0]["human_verdict"] == "wrong"
        assert reloaded["generated"] == "2026-06-04T00:00:00Z"
