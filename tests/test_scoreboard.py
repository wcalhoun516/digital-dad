"""The scoreboard core: read the eval reports, say whether this run beat the last one."""

import json

import pytest

from analysis import scoreboard


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def voice_report(
    *,
    ft_win_rate=0.0,
    ft_avg_rank=2.88,
    ft_ttr=0.35,
    ft_hinge=101.0,
    real_ttr=0.70,
    real_hinge=46.0,
):
    """A `voice_eval.json` payload in the real shape written by `voice_eval.write_report`."""
    return {
        "generated_at": "2026-09-22T00:00:00+00:00",
        "summary": {
            "n_trials": 8,
            "n_judged": 8,
            "sources": {
                "finetune": {
                    "appearances": 8,
                    "wins": 0,
                    "win_rate": ft_win_rate,
                    "avg_rank": ft_avg_rank,
                },
                "real": {
                    "appearances": 8,
                    "wins": 5,
                    "win_rate": 0.625,
                    "avg_rank": 1.63,
                },
            },
            "pairwise": {"real_over_finetune": 1.0},
            "style": {
                "n_trials": 8,
                "sources": {
                    "finetune": {
                        "appearances": 8,
                        "mean": {
                            "word_count": 300.0,
                            "type_token_ratio": ft_ttr,
                            "avg_sentence_len": 21.0,
                            "fingerprint_hits_per_1k": ft_hinge,
                        },
                    },
                    "real": {
                        "appearances": 8,
                        "mean": {
                            "word_count": 900.0,
                            "type_token_ratio": real_ttr,
                            "avg_sentence_len": 24.0,
                            "fingerprint_hits_per_1k": real_hinge,
                        },
                    },
                },
            },
        },
        "records": [],
    }


class TestReadReport:
    """A report the operator has never generated is an absence, not a crash."""

    def test_reads_the_summary_of_a_real_report(self, tmp_path):
        path = write_json(tmp_path / "voice_eval.json", voice_report())
        assert scoreboard.read_report(path)["summary"]["n_trials"] == 8

    def test_a_missing_report_is_none(self, tmp_path):
        assert scoreboard.read_report(tmp_path / "never_run.json") is None

    def test_malformed_json_is_none_not_a_traceback(self, tmp_path):
        path = tmp_path / "half_written.json"
        path.write_text('{"summary": {"n_tri')
        assert scoreboard.read_report(path) is None

    def test_a_report_without_a_summary_is_none(self, tmp_path):
        path = write_json(tmp_path / "wrong.json", {"records": []})
        assert scoreboard.read_report(path) is None


class TestVoiceScores:
    """Flatten `voice_eval`'s nested summary into one row per source."""

    def test_pulls_win_rate_and_avg_rank_per_source(self, tmp_path):
        report = voice_report(ft_win_rate=0.25, ft_avg_rank=2.0)
        scores = scoreboard.voice_scores(report)
        assert scores["finetune"]["win_rate"] == 0.25
        assert scores["finetune"]["avg_rank"] == 2.0

    def test_pulls_style_metrics_from_the_nested_style_block(self, tmp_path):
        scores = scoreboard.voice_scores(voice_report(ft_ttr=0.41, ft_hinge=88.0))
        assert scores["finetune"]["type_token_ratio"] == 0.41
        assert scores["finetune"]["fingerprint_hits_per_1k"] == 88.0

    def test_a_style_less_report_still_yields_ranking_metrics(self):
        """The paid judge runs without style when `voice-style` was never run."""
        report = voice_report()
        del report["summary"]["style"]
        scores = scoreboard.voice_scores(report)
        assert scores["finetune"]["win_rate"] == 0.0
        assert "type_token_ratio" not in scores["finetune"]

    def test_a_source_scored_only_for_style_still_appears(self):
        """`make voice-style` writes style with no judge ranking at all."""
        report = voice_report()
        report["summary"]["sources"] = {}
        scores = scoreboard.voice_scores(report)
        assert scores["finetune"]["type_token_ratio"] == 0.35
        assert "win_rate" not in scores["finetune"]

    def test_no_report_is_an_empty_mapping(self):
        assert scoreboard.voice_scores(None) == {}


class TestRagScores:
    def test_pulls_the_faithfulness_headlines(self):
        report = {
            "generated_at": "2026-09-22T00:00:00+00:00",
            "summary": {
                "n_questions": 20,
                "grounding_rate": 0.91,
                "hallucination_rate": 0.09,
                "abstention_accuracy": 0.8,
                "citation_coverage": 0.75,
            },
        }
        scores = scoreboard.rag_scores(report)
        assert scores["grounding_rate"] == 0.91
        assert scores["citation_coverage"] == 0.75

    def test_no_report_is_an_empty_mapping(self):
        assert scoreboard.rag_scores(None) == {}


class TestPreflightScores:
    def test_pulls_the_over_budget_percentage(self):
        report = {
            "ok": False,
            "checks": {
                "length_budget": {
                    "ok": False,
                    "n": 540,
                    "n_over": 54,
                    "pct_over": 10.0,
                    "max_seq_len": 2048,
                }
            },
        }
        scores = scoreboard.preflight_scores(report)
        assert scores["pct_over"] == 10.0
        assert scores["n_over"] == 54
        assert scores["max_seq_len"] == 2048

    def test_a_preflight_without_a_length_budget_is_empty(self):
        assert scoreboard.preflight_scores({"checks": {}}) == {}

    def test_no_report_is_an_empty_mapping(self):
        assert scoreboard.preflight_scores(None) == {}
