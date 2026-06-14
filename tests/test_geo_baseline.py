"""Tests for analysis/geo_baseline.py — the Geo-LLM baseline snapshot (plan 0008 step 26b).

Pure shaping/formatting logic only: turn the #25 RAG eval output (rag_eval.json) into a
curated "bar to beat" baseline artifact + a markdown note. No conductor, no I/O against
the live harness — a fixture summary stands in for a real eval run.
"""

import json

from analysis.geo_baseline import (
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    build_baseline,
    compare_to_targets,
    load_rag_summary,
    render_markdown,
)

FIXTURE_RAG_EVAL = {
    "generated_at": "2026-06-13T12:44:12.396902+00:00",
    "summary": {
        "n_questions": 14,
        "n_answerable": 10,
        "n_unanswerable": 4,
        "total_claims": 75,
        "grounded_claims": 64,
        "grounding_rate": 0.8533,
        "hallucination_rate": 0.1467,
        "abstention_accuracy": 1.0,
        "false_abstention_rate": 0.1,
        "citation_coverage": 0.6,
    },
}


class TestBuildBaseline:
    def _baseline(self):
        return build_baseline(FIXTURE_RAG_EVAL, captured_at="2026-06-14T00:00:00+00:00")

    def test_factuality_metrics_copied_from_summary(self):
        b = self._baseline()
        f = b["factuality"]
        assert f["grounding_rate"] == 0.8533
        assert f["hallucination_rate"] == 0.1467
        assert f["abstention_accuracy"] == 1.0
        assert f["false_abstention_rate"] == 0.1
        assert f["citation_coverage"] == 0.6
        assert f["total_claims"] == 75
        assert f["grounded_claims"] == 64

    def test_provenance_points_back_to_rag_eval(self):
        b = self._baseline()
        assert b["captured_at"] == "2026-06-14T00:00:00+00:00"
        assert b["source"]["rag_eval_generated_at"] == "2026-06-13T12:44:12.396902+00:00"
        assert b["source"]["n_questions"] == 14
        assert "rag_eval" in b["source"]["harness"]

    def test_voice_slot_is_pending(self):
        b = self._baseline()
        assert b["voice"]["status"] == "pending"
        assert "26d" in b["voice"]["note"]

    def test_targets_encode_direction_and_bar(self):
        targets = self._baseline()["targets"]
        # the four faithfulness metrics a fine-tune must not regress on
        assert set(targets) == {
            "grounding_rate",
            "hallucination_rate",
            "abstention_accuracy",
            "false_abstention_rate",
        }
        assert targets["grounding_rate"]["direction"] == HIGHER_IS_BETTER
        assert targets["grounding_rate"]["must_beat"] == 0.8533
        assert targets["hallucination_rate"]["direction"] == LOWER_IS_BETTER
        assert targets["hallucination_rate"]["must_beat"] == 0.1467

    def test_roundtrips_as_json(self):
        # the artifact must be serializable as-is
        json.dumps(self._baseline())


class TestBuildBaselinePartial:
    def test_omits_targets_for_absent_metrics(self):
        partial = {"generated_at": "2026-06-13T00:00:00+00:00", "summary": {"grounding_rate": 0.9}}
        b = build_baseline(partial, captured_at="2026-06-14T00:00:00+00:00")
        # only the present metric gets a target; no KeyError on the missing ones
        assert set(b["targets"]) == {"grounding_rate"}
        assert b["factuality"] == {"grounding_rate": 0.9}


class TestCompareToTargets:
    def _baseline(self):
        return build_baseline(FIXTURE_RAG_EVAL, captured_at="2026-06-14T00:00:00+00:00")

    def test_strictly_better_passes_all(self):
        candidate = {
            "grounding_rate": 0.90,       # > 0.8533
            "hallucination_rate": 0.10,   # < 0.1467
            "abstention_accuracy": 1.0,   # must strictly beat 1.0 -> impossible, see next test
            "false_abstention_rate": 0.05,
        }
        result = compare_to_targets(self._baseline(), candidate)
        # abstention can't strictly beat a perfect 1.0, so not all_passed here
        assert result["per_metric"]["grounding_rate"]["passed"] is True
        assert result["per_metric"]["hallucination_rate"]["passed"] is True
        assert result["per_metric"]["abstention_accuracy"]["passed"] is False

    def test_matching_the_bar_does_not_count_as_beating(self):
        candidate = {
            "grounding_rate": 0.8533,
            "hallucination_rate": 0.1467,
            "abstention_accuracy": 1.0,
            "false_abstention_rate": 0.1,
        }
        result = compare_to_targets(self._baseline(), candidate)
        assert all(not m["passed"] for m in result["per_metric"].values())
        assert result["all_passed"] is False

    def test_signed_deltas(self):
        candidate = {
            "grounding_rate": 0.90,
            "hallucination_rate": 0.10,
            "abstention_accuracy": 1.0,
            "false_abstention_rate": 0.05,
        }
        per = compare_to_targets(self._baseline(), candidate)["per_metric"]
        assert round(per["grounding_rate"]["delta"], 4) == round(0.90 - 0.8533, 4)
        assert round(per["false_abstention_rate"]["delta"], 4) == round(0.05 - 0.1, 4)

    def test_missing_candidate_metric_blocks_pass(self):
        candidate = {"grounding_rate": 0.99}  # the rest absent
        result = compare_to_targets(self._baseline(), candidate)
        assert "hallucination_rate" in result["missing"]
        assert result["all_passed"] is False


class TestRenderMarkdown:
    def test_includes_headline_numbers_and_framing(self):
        baseline = build_baseline(FIXTURE_RAG_EVAL, captured_at="2026-06-14T00:00:00+00:00")
        md = render_markdown(baseline)
        assert "85.3%" in md  # grounding rate
        assert "14.7%" in md  # hallucination rate
        assert "pending" in md.lower()  # voice slot
        assert "beat" in md.lower()  # the framing
        # provenance is cited
        assert "2026-06-13" in md


class TestLoadRagSummary:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_rag_summary(tmp_path / "nope.json") is None

    def test_reads_full_object(self, tmp_path):
        p = tmp_path / "rag_eval.json"
        p.write_text(json.dumps(FIXTURE_RAG_EVAL))
        loaded = load_rag_summary(p)
        assert loaded["summary"]["grounding_rate"] == 0.8533
        assert loaded["generated_at"].startswith("2026-06-13")

    def test_malformed_json_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert load_rag_summary(p) is None
