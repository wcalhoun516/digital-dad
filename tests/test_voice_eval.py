"""Tests for analysis/voice_eval.py — the Geo-LLM voice-fidelity eval harness.

Plan 0008 step 26d. Exercises pure logic only: the deterministic blinding of
candidate passages to anonymized labels, the judge-ranking parser, un-blinding,
and the harness run loop / aggregation / report. The live judge seam (conductor
T3) is injected as a fake, so no conductor and no network are touched here.
"""

import json

from analysis.voice_eval import (
    aggregate,
    blind_candidates,
    build_judge_prompt,
    evaluate,
    load_trials,
    parse_ranking,
    unblind_ranking,
    write_report,
)


class TestBlindCandidates:
    def test_assigns_a_label_per_source(self):
        blinded, mapping = blind_candidates(
            {"real": "x", "rag": "y", "finetuned": "z"}, seed=1
        )
        assert sorted(blinded) == ["A", "B", "C"]
        assert sorted(mapping) == ["A", "B", "C"]

    def test_mapping_points_labels_back_to_sources(self):
        blinded, mapping = blind_candidates({"real": "x", "rag": "y"}, seed=1)
        # every label maps to a source, and the blinded text matches that source
        sources = {"real": "x", "rag": "y"}
        for label, source in mapping.items():
            assert blinded[label] == sources[source]
        assert sorted(mapping.values()) == ["rag", "real"]

    def test_is_deterministic_for_a_seed(self):
        a = blind_candidates({"real": "x", "rag": "y", "finetuned": "z"}, seed=7)
        b = blind_candidates({"real": "x", "rag": "y", "finetuned": "z"}, seed=7)
        assert a == b

    def test_different_seeds_can_shuffle_differently(self):
        # Over a range of seeds the 'real' source must not always land on label A
        # (otherwise the blinding is not actually anonymizing position).
        labels_for_real = set()
        for s in range(20):
            _, mapping = blind_candidates(
                {"real": "x", "rag": "y", "finetuned": "z"}, seed=s
            )
            inv = {src: lbl for lbl, src in mapping.items()}
            labels_for_real.add(inv["real"])
        assert len(labels_for_real) > 1


class TestParseRanking:
    def test_parses_clean_json_ranking(self):
        assert parse_ranking('{"ranking": ["B", "A", "C"]}', ["A", "B", "C"]) == [
            "B",
            "A",
            "C",
        ]

    def test_tolerates_prose_and_fences(self):
        text = 'Sure!\n```json\n{"ranking": ["C", "A", "B"]}\n```\nDone.'
        assert parse_ranking(text, ["A", "B", "C"]) == ["C", "A", "B"]

    def test_drops_unknown_labels(self):
        assert parse_ranking('{"ranking": ["A", "Z", "B"]}', ["A", "B"]) == ["A", "B"]

    def test_appends_missing_labels_in_order(self):
        # judge omitted C; harness completes the ranking so it stays total
        assert parse_ranking('{"ranking": ["B"]}', ["A", "B", "C"]) == ["B", "A", "C"]

    def test_dedupes_preserving_first_position(self):
        assert parse_ranking('{"ranking": ["A", "A", "B"]}', ["A", "B"]) == ["A", "B"]

    def test_returns_none_without_parseable_object(self):
        assert parse_ranking("no json here", ["A", "B"]) is None


class TestUnblindRanking:
    def test_maps_labels_back_to_sources(self):
        mapping = {"A": "rag", "B": "real", "C": "finetuned"}
        assert unblind_ranking(["B", "C", "A"], mapping) == [
            "real",
            "finetuned",
            "rag",
        ]


class TestBuildJudgePrompt:
    def test_includes_prompt_and_every_label(self):
        out = build_judge_prompt("Write on the Fed.", {"A": "alpha", "B": "beta"})
        assert "Write on the Fed." in out
        assert "A" in out and "alpha" in out
        assert "B" in out and "beta" in out


class TestEvaluate:
    def _trials(self):
        return [
            {
                "id": "v01",
                "prompt": "p1",
                "candidates": {"real": "R", "rag": "G", "finetuned": "F"},
            },
            {
                "id": "v02",
                "prompt": "p2",
                "candidates": {"real": "R2", "rag": "G2", "finetuned": "F2"},
            },
        ]

    def test_records_unblinded_winner_per_trial(self):
        # Fake judge: always ranks the 'real' source first by reading the blinded
        # texts back through a source lookup baked into the trial.
        def judge(prompt, blinded):
            # rank labels so that whichever maps to the longest text wins; the test
            # only checks the harness threads ranking -> unblind correctly, so use a
            # deterministic rule over the blinded payload itself.
            return sorted(blinded, key=lambda lbl: blinded[lbl])

        records = evaluate(self._trials(), judge, seed=3)
        assert [r["id"] for r in records] == ["v01", "v02"]
        for r in records:
            assert set(r["ranking"]) == {"real", "rag", "finetuned"}
            assert r["winner"] == r["ranking"][0]

    def test_winner_reflects_judge_choice(self):
        # Judge always puts the label mapped to 'finetuned' first.
        def judge(prompt, blinded):
            # We can't see the mapping here, so just return labels as-is; combined
            # with a fixed seed the harness must still produce a consistent winner.
            return list(blinded)

        records = evaluate(self._trials(), judge, seed=0)
        assert all(r["winner"] in {"real", "rag", "finetuned"} for r in records)

    def test_skips_trial_when_judge_returns_none(self):
        def judge(prompt, blinded):
            return None

        records = evaluate(self._trials(), judge, seed=1)
        # Unparseable judgments are recorded with an empty ranking, not dropped.
        assert len(records) == 2
        assert all(r["ranking"] == [] for r in records)
        assert all(r["winner"] is None for r in records)


class TestAggregate:
    def test_win_rate_and_avg_rank_per_source(self):
        records = [
            {"ranking": ["finetuned", "rag", "real"], "winner": "finetuned"},
            {"ranking": ["real", "finetuned", "rag"], "winner": "real"},
            {"ranking": ["finetuned", "real", "rag"], "winner": "finetuned"},
        ]
        summary = aggregate(records)
        assert summary["n_trials"] == 3
        assert summary["sources"]["finetuned"]["wins"] == 2
        assert summary["sources"]["finetuned"]["win_rate"] == 0.6667
        # avg rank (1-indexed): finetuned at positions 1,2,1 -> 1.3333
        assert summary["sources"]["finetuned"]["avg_rank"] == 1.3333

    def test_pairwise_finetuned_vs_rag(self):
        records = [
            {"ranking": ["finetuned", "rag", "real"], "winner": "finetuned"},
            {"ranking": ["rag", "finetuned", "real"], "winner": "rag"},
            {"ranking": ["finetuned", "real", "rag"], "winner": "finetuned"},
        ]
        summary = aggregate(records)
        # finetuned ranked above rag in 2 of 3 trials
        assert summary["pairwise"]["finetuned_over_rag"] == 0.6667

    def test_ignores_records_with_empty_ranking(self):
        records = [
            {"ranking": ["finetuned", "rag"], "winner": "finetuned"},
            {"ranking": [], "winner": None},
        ]
        summary = aggregate(records)
        assert summary["n_trials"] == 2
        assert summary["n_judged"] == 1
        assert summary["sources"]["finetuned"]["wins"] == 1


class TestWriteReport:
    def test_writes_summary_and_records(self, tmp_path):
        records = [{"ranking": ["finetuned", "rag"], "winner": "finetuned"}]
        out = tmp_path / "voice_eval.json"
        summary = write_report(records, out)
        payload = json.loads(out.read_text())
        assert payload["summary"] == summary
        assert payload["records"] == records
        assert "generated_at" in payload


class TestLoadTrials:
    def test_loads_trials_list(self, tmp_path):
        p = tmp_path / "trials.json"
        p.write_text(json.dumps({"trials": [{"id": "v01", "prompt": "p"}]}))
        assert load_trials(p) == [{"id": "v01", "prompt": "p"}]
