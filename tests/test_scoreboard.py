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


class TestDirections:
    """Which way is better is a property of the metric, not of the reader."""

    def test_every_metric_the_readers_surface_declares_a_direction(self):
        """A metric with no direction would render as an unlabelled signed number."""
        surfaced = set(scoreboard._RANK_KEYS + scoreboard._STYLE_KEYS + scoreboard._RAG_KEYS)
        surfaced |= set(scoreboard._PREFLIGHT_KEYS)
        scored = {m for m in surfaced if m in scoreboard.DIRECTIONS}
        assert scored, "no metric has a direction"
        for metric in scored:
            assert scoreboard.DIRECTIONS[metric] in {"higher", "lower", "toward"}


class TestCompare:
    def test_a_rise_in_win_rate_is_better(self):
        result = scoreboard.compare("win_rate", 0.25, 0.0)
        assert result["verdict"] == "better"
        assert result["delta"] == pytest.approx(0.25)

    def test_a_rise_in_avg_rank_is_worse_because_rank_one_wins(self):
        assert scoreboard.compare("avg_rank", 2.5, 2.0)["verdict"] == "worse"

    def test_a_fall_in_avg_rank_is_better(self):
        assert scoreboard.compare("avg_rank", 1.4, 2.88)["verdict"] == "better"

    def test_a_fall_in_hallucination_rate_is_better(self):
        assert scoreboard.compare("hallucination_rate", 0.05, 0.2)["verdict"] == "better"

    def test_no_change_is_flat(self):
        assert scoreboard.compare("win_rate", 0.5, 0.5)["verdict"] == "flat"

    def test_nothing_to_compare_against_is_unknown(self):
        result = scoreboard.compare("win_rate", 0.5, None)
        assert result["verdict"] == "unknown"
        assert result["delta"] is None

    def test_an_unknown_metric_is_unscored_rather_than_guessed(self):
        assert scoreboard.compare("word_count", 900, 300)["verdict"] == "unscored"


class TestCompareTowardATarget:
    """TTR and hinge-word rate are not 'more is better' — they have a right answer.

    D15's finding was that the fine-tune used his distinctive vocabulary at ~2x the
    natural rate. A scoreboard that scored that metric 'lower is better' would reward
    a model that had lost his vocabulary altogether, which is the opposite of the goal.
    """

    def test_closing_the_gap_to_the_target_is_better(self):
        result = scoreboard.compare(
            "type_token_ratio", 0.55, 0.35, target=0.70
        )
        assert result["verdict"] == "better"

    def test_overshooting_the_target_is_worse_even_though_the_number_rose(self):
        result = scoreboard.compare("type_token_ratio", 0.80, 0.65, target=0.70)
        assert result["verdict"] == "worse"

    def test_falling_toward_the_target_from_above_is_better(self):
        """Hinge-word over-use at 101 vs a natural 46: coming down is the fix."""
        result = scoreboard.compare(
            "fingerprint_hits_per_1k", 60.0, 101.0, target=46.0
        )
        assert result["verdict"] == "better"
        assert result["gap"] == pytest.approx(14.0)

    def test_a_toward_metric_without_a_target_is_unscored(self):
        result = scoreboard.compare("type_token_ratio", 0.55, 0.35)
        assert result["verdict"] == "unscored"

    def test_an_equal_gap_on_the_other_side_is_flat(self):
        result = scoreboard.compare("type_token_ratio", 0.75, 0.65, target=0.70)
        assert result["verdict"] == "flat"


class TestBaseline:
    """D15's numbers are the record every future run has to beat."""

    def test_records_the_finetunes_standing_defeat(self):
        finetune = scoreboard.BASELINE["voice"]["finetune"]
        assert finetune["win_rate"] == 0.0
        assert finetune["avg_rank"] == 2.88

    def test_records_the_rag_and_real_ranks_that_tied_at_the_top(self):
        assert scoreboard.BASELINE["voice"]["rag"]["avg_rank"] == 1.50
        assert scoreboard.BASELINE["voice"]["real"]["avg_rank"] == 1.63

    def test_records_the_style_gap_that_explained_the_loss(self):
        voice = scoreboard.BASELINE["voice"]
        assert voice["finetune"]["type_token_ratio"] == 0.35
        assert voice["real"]["type_token_ratio"] == 0.70

    def test_names_the_adr_it_came_from(self):
        assert scoreboard.BASELINE["adr"] == "D15"


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
