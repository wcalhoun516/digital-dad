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


def history_row(arm, *, date="2026-09-19", experiment="A_plain", win_rate=0.0, avg_rank=2.5):
    """One row of `voice_eval_history.jsonl` — one arm within one run."""
    return {
        "adr": "D20",
        "arm": arm,
        "avg_rank": avg_rank,
        "condition": "no-retrieval",
        "corpus": {"articles": 181, "approx_tokens": 453000, "train_records": 540},
        "date": date,
        "experiment": experiment,
        "judge_tier": 3,
        "n_trials": 8,
        "training": None,
        "win_rate": win_rate,
    }


class TestGroupRuns:
    """The history is one row per *arm*; a run is the group of arms judged together."""

    def test_rows_sharing_a_date_experiment_and_condition_are_one_run(self):
        rows = [history_row("real"), history_row("gemma-ft"), history_row("gemma-plain")]
        runs = scoreboard.group_runs(rows)
        assert len(runs) == 1
        assert sorted(runs[0]["arms"]) == ["gemma-ft", "gemma-plain", "real"]

    def test_a_different_experiment_is_a_different_run(self):
        rows = [history_row("real"), history_row("real", experiment="B_rag")]
        assert len(scoreboard.group_runs(rows)) == 2

    def test_each_arm_keeps_its_scores(self):
        rows = [history_row("real", win_rate=1.0, avg_rank=1.0)]
        arm = scoreboard.group_runs(rows)[0]["arms"]["real"]
        assert arm["win_rate"] == 1.0
        assert arm["avg_rank"] == 1.0

    def test_a_run_carries_the_corpus_size_it_was_scored_at(self):
        """'How much text is enough' is the question the series exists to answer."""
        run = scoreboard.group_runs([history_row("real")])[0]
        assert run["corpus"]["articles"] == 181

    def test_runs_come_back_oldest_first(self):
        rows = [
            history_row("real", date="2026-09-01"),
            history_row("real", date="2026-09-19"),
        ]
        assert [r["date"] for r in scoreboard.group_runs(rows)] == [
            "2026-09-01",
            "2026-09-19",
        ]

    def test_an_empty_history_is_no_runs(self):
        assert scoreboard.group_runs([]) == []

    def test_a_row_without_an_arm_is_skipped_rather_than_grouped_under_none(self):
        runs = scoreboard.group_runs([{"date": "2026-09-19"}, history_row("real")])
        assert len(runs) == 1
        assert list(runs[0]["arms"]) == ["real"]

    def test_the_real_history_file_groups_into_its_four_experiments(self):
        """Pinned against the committed series so a shape change here is loud."""
        rows = [
            history_row("real", experiment=name)
            for name in ("A_plain", "B_rag", "C_shot", "D_shot_rag")
        ]
        assert [r["experiment"] for r in scoreboard.group_runs(rows)] == [
            "A_plain",
            "B_rag",
            "C_shot",
            "D_shot_rag",
        ]


class TestRunDeltas:
    """Arm-by-arm, did this run beat the previous one?"""

    def test_scores_each_arm_against_its_own_previous_result(self):
        previous = scoreboard.group_runs([history_row("gemma-ft", win_rate=0.0)])[0]
        current = scoreboard.group_runs(
            [history_row("gemma-ft", win_rate=0.25, date="2026-09-22")]
        )[0]
        deltas = scoreboard.run_deltas(current, previous)
        assert deltas["gemma-ft"]["win_rate"]["verdict"] == "better"

    def test_an_arm_that_is_new_this_run_has_nothing_to_beat(self):
        previous = scoreboard.group_runs([history_row("real")])[0]
        current = scoreboard.group_runs(
            [history_row("real"), history_row("gemma-ft", date="2026-09-19")]
        )[0]
        deltas = scoreboard.run_deltas(current, previous)
        assert deltas["gemma-ft"]["win_rate"]["verdict"] == "unknown"

    def test_with_no_previous_run_every_arm_is_unknown(self):
        current = scoreboard.group_runs([history_row("real")])[0]
        deltas = scoreboard.run_deltas(current, None)
        assert deltas["real"]["avg_rank"]["verdict"] == "unknown"


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


class TestStyleTarget:
    """What 'his real prose' scores at is measured fresh, not remembered."""

    def test_the_target_is_the_real_source_in_the_current_report(self):
        scores = scoreboard.voice_scores(voice_report(real_ttr=0.66))
        assert scoreboard.style_target(scores, "type_token_ratio") == 0.66

    def test_it_falls_back_to_the_baselines_real_corpus_when_unmeasured(self):
        """A style-less run still has D15's recorded real numbers to aim at."""
        assert scoreboard.style_target({}, "type_token_ratio") == 0.70
        assert scoreboard.style_target({}, "fingerprint_hits_per_1k") == 46.0

    def test_an_unknown_style_metric_has_no_target(self):
        assert scoreboard.style_target({}, "word_count") is None


class TestVsBaseline:
    """Every run is read against the record it has to beat."""

    def test_a_finetune_that_now_wins_a_quarter_of_trials_beats_d15(self):
        scores = scoreboard.voice_scores(voice_report(ft_win_rate=0.25))
        against = scoreboard.vs_baseline(scores)
        assert against["finetune"]["win_rate"]["verdict"] == "better"
        assert against["finetune"]["win_rate"]["previous"] == 0.0

    def test_a_finetune_still_ranking_last_has_not_moved(self):
        against = scoreboard.vs_baseline(scoreboard.voice_scores(voice_report()))
        assert against["finetune"]["avg_rank"]["verdict"] == "flat"

    def test_closing_the_lexical_diversity_gap_reads_as_better(self):
        """D15: the fine-tune's TTR was half the real corpus. Catching up is the win."""
        scores = scoreboard.voice_scores(voice_report(ft_ttr=0.60))
        against = scoreboard.vs_baseline(scores)
        assert against["finetune"]["type_token_ratio"]["verdict"] == "better"

    def test_calming_the_hinge_word_overuse_reads_as_better(self):
        scores = scoreboard.voice_scores(voice_report(ft_hinge=55.0))
        against = scoreboard.vs_baseline(scores)
        assert against["finetune"]["fingerprint_hits_per_1k"]["verdict"] == "better"

    def test_a_source_d15_never_scored_is_reported_as_unknown(self):
        report = voice_report()
        report["summary"]["sources"]["gemma-shot"] = {"win_rate": 0.5, "avg_rank": 1.2}
        against = scoreboard.vs_baseline(scoreboard.voice_scores(report))
        assert against["gemma-shot"]["win_rate"]["verdict"] == "unknown"


class TestScoreboard:
    """The assembled payload a console route will hand straight to the page."""

    def test_reports_every_section_even_when_nothing_has_been_run(self, tmp_path):
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=[],
        )
        assert board["voice"]["sources"] == {}
        assert board["rag"] == {}
        assert board["runs"] == []
        assert board["baseline"]["adr"] == "D15"

    def test_carries_the_current_and_previous_run_and_their_deltas(self, tmp_path):
        history = [
            history_row("gemma-ft", date="2026-09-01", win_rate=0.0),
            history_row("gemma-ft", date="2026-09-19", win_rate=0.25),
        ]
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=history,
        )
        assert board["current_run"]["date"] == "2026-09-19"
        assert board["previous_run"]["date"] == "2026-09-01"
        assert board["run_deltas"]["gemma-ft"]["win_rate"]["verdict"] == "better"

    def test_the_previous_run_is_the_last_one_of_the_same_experiment(self, tmp_path):
        """The history interleaves conditions, so "the row before" is the wrong run.

        D20 recorded a 2x2 on a single day: A_plain, B_rag, C_shot, D_shot_rag. The
        run before D_shot_rag is C_shot — a different condition with differently named
        arms. Comparing them would read as "every arm is new", or worse, as a delta
        between two things that were never alternatives.
        """
        history = [
            history_row("gemma-ft", date="2026-09-01", experiment="A_plain", win_rate=0.0),
            history_row("gemma-ft", date="2026-09-19", experiment="B_rag", win_rate=0.9),
            history_row("gemma-ft", date="2026-09-22", experiment="A_plain", win_rate=0.25),
        ]
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=history,
        )
        assert board["current_run"]["experiment"] == "A_plain"
        assert board["previous_run"]["date"] == "2026-09-01"
        assert board["run_deltas"]["gemma-ft"]["win_rate"]["verdict"] == "better"

    def test_the_newest_run_of_an_experiment_never_seen_before_has_no_previous(
        self, tmp_path
    ):
        history = [
            history_row("gemma-ft", date="2026-09-01", experiment="A_plain"),
            history_row("gemma-ft", date="2026-09-22", experiment="D_shot_rag"),
        ]
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=history,
        )
        assert board["current_run"]["experiment"] == "D_shot_rag"
        assert board["previous_run"] is None

    def test_an_experiment_can_be_named_to_score_a_series_directly(self, tmp_path):
        history = [
            history_row("gemma-ft", date="2026-09-01", experiment="A_plain", win_rate=0.0),
            history_row("gemma-ft", date="2026-09-02", experiment="A_plain", win_rate=0.4),
            history_row("gemma-ft", date="2026-09-22", experiment="D_shot_rag"),
        ]
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=history,
            experiment="A_plain",
        )
        assert board["current_run"]["date"] == "2026-09-02"
        assert board["previous_run"]["date"] == "2026-09-01"

    def test_a_single_run_has_no_previous_to_compare_against(self, tmp_path):
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=[history_row("real")],
        )
        assert board["previous_run"] is None
        assert board["run_deltas"]["real"]["win_rate"]["verdict"] == "unknown"

    def test_reads_the_reports_from_disk(self, tmp_path):
        write_json(tmp_path / "voice_eval.json", voice_report(ft_win_rate=0.5))
        write_json(
            tmp_path / "rag_eval.json",
            {"summary": {"grounding_rate": 0.9, "n_questions": 20}},
        )
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "voice_eval.json",
            rag_path=tmp_path / "rag_eval.json",
            history=[],
        )
        assert board["voice"]["sources"]["finetune"]["win_rate"] == 0.5
        assert board["voice"]["vs_baseline"]["finetune"]["win_rate"]["verdict"] == "better"
        assert board["rag"]["grounding_rate"] == 0.9

    def test_a_preflight_report_contributes_its_over_budget_percentage(self, tmp_path):
        board = scoreboard.scoreboard(
            voice_path=tmp_path / "none.json",
            rag_path=tmp_path / "none.json",
            history=[],
            preflight={"checks": {"length_budget": {"pct_over": 12.5, "n_over": 7}}},
        )
        assert board["preflight"]["pct_over"] == 12.5


class TestCli:
    def test_prints_a_json_payload(self, tmp_path, capsys):
        write_json(tmp_path / "voice_eval.json", voice_report(ft_win_rate=0.5))
        code = scoreboard.main(
            [
                "--voice-report",
                str(tmp_path / "voice_eval.json"),
                "--rag-report",
                str(tmp_path / "absent.json"),
                "--history",
                str(tmp_path / "absent.jsonl"),
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["voice"]["sources"]["finetune"]["win_rate"] == 0.5
        assert payload["baseline"]["adr"] == "D15"


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
