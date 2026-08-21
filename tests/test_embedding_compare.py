"""Tests for analysis/embedding_compare.py — the embedding-model comparison harness (#27).

Exercises pure logic only: the cosine-ranking core, the retrieval-quality metrics
(precision@k / recall@k / MRR) against a gold query set, the baseline-agreement
metrics (top-k overlap / Kendall-tau) that need no labels, and the harness run
loop / aggregation / report. The one compute-heavy seam — actually embedding text
with a candidate model — is injected as a fake, so no conductor and no network are
touched here.
"""

import json
import math

import numpy as np

from analysis.embedding_compare import (
    aggregate,
    compare_models,
    kendall_tau,
    load_corpus_slugs,
    load_queries,
    main,
    mrr,
    overlap_at_k,
    paired_comparison,
    per_query_metrics,
    precision_at_k,
    rank_slugs,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
    unknown_models,
    validate_queries,
    write_report,
)

# --------------------------------------------------------------------------- #
# Ranking core
# --------------------------------------------------------------------------- #

class TestRankSlugs:
    def test_ranks_by_descending_cosine(self):
        corpus = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        slugs = ["x", "y", "diag"]
        # query aligned with the x-axis: "x" is most similar, "y" least.
        ranked = rank_slugs(np.array([1.0, 0.0]), corpus, slugs)
        assert ranked[0] == "x"
        assert ranked[-1] == "y"

    def test_magnitude_invariant(self):
        # cosine ignores vector length; a scaled query gives the same order.
        corpus = np.array([[1.0, 0.0], [0.0, 1.0], [2.0, 1.0]])
        slugs = ["a", "b", "c"]
        assert rank_slugs(np.array([1.0, 0.0]), corpus, slugs) == rank_slugs(
            np.array([5.0, 0.0]), corpus, slugs
        )

    def test_returns_all_slugs(self):
        corpus = np.array([[1.0, 0.0], [0.0, 1.0]])
        ranked = rank_slugs(np.array([1.0, 1.0]), corpus, ["a", "b"])
        assert sorted(ranked) == ["a", "b"]

    def test_zero_query_vector_does_not_crash(self):
        corpus = np.array([[1.0, 0.0], [0.0, 1.0]])
        ranked = rank_slugs(np.array([0.0, 0.0]), corpus, ["a", "b"])
        assert sorted(ranked) == ["a", "b"]


# --------------------------------------------------------------------------- #
# Retrieval-quality metrics
# --------------------------------------------------------------------------- #

class TestPrecisionAtK:
    def test_all_relevant_in_top_k(self):
        assert precision_at_k(["a", "b", "c"], {"a", "b"}, 2) == 1.0

    def test_none_relevant(self):
        assert precision_at_k(["a", "b", "c"], {"z"}, 2) == 0.0

    def test_partial(self):
        assert precision_at_k(["a", "x", "b"], {"a", "b"}, 2) == 0.5

    def test_k_larger_than_ranking(self):
        # denominator is min(k, len(ranking)); one hit out of two available slots.
        assert precision_at_k(["a", "x"], {"a"}, 5) == 0.5

    def test_empty_ranking(self):
        assert precision_at_k([], {"a"}, 3) == 0.0


class TestRecallAtK:
    def test_all_relevant_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, 3) == 1.0

    def test_partial(self):
        assert recall_at_k(["a", "x", "y"], {"a", "b"}, 3) == 0.5

    def test_no_relevant_defined(self):
        assert recall_at_k(["a", "b"], set(), 2) == 0.0


class TestReciprocalRankAndMRR:
    def test_first_relevant_at_rank_1(self):
        assert reciprocal_rank(["a", "b"], {"a"}) == 1.0

    def test_first_relevant_at_rank_3(self):
        assert reciprocal_rank(["x", "y", "a"], {"a"}) == 1 / 3

    def test_no_relevant_hit(self):
        assert reciprocal_rank(["x", "y"], {"a"}) == 0.0

    def test_mrr_averages_over_queries(self):
        rankings = [["a", "b"], ["x", "a"]]  # RR = 1, then 1/2
        relevants = [{"a"}, {"a"}]
        assert mrr(rankings, relevants) == (1.0 + 0.5) / 2

    def test_mrr_empty(self):
        assert mrr([], []) == 0.0


class TestRetrievalMetrics:
    def test_reports_precision_recall_mrr(self):
        rankings = [["a", "b", "c"], ["b", "a", "c"]]
        relevants = [{"a"}, {"a"}]
        out = retrieval_metrics(rankings, relevants, ks=(1, 2))
        assert out["mrr"] == (1.0 + 0.5) / 2
        assert out["precision_at_1"] == (1.0 + 0.0) / 2
        assert out["recall_at_2"] == 1.0
        assert out["n_scored"] == 2

    def test_skips_queries_without_labels(self):
        # A query with no relevant slugs isn't scorable and is excluded from means.
        rankings = [["a", "b"], ["x", "y"]]
        relevants = [{"a"}, set()]
        out = retrieval_metrics(rankings, relevants, ks=(1,))
        assert out["n_scored"] == 1
        assert out["precision_at_1"] == 1.0

    def test_no_labels_at_all(self):
        out = retrieval_metrics([["a"]], [set()], ks=(1,))
        assert out["n_scored"] == 0
        assert out["mrr"] == 0.0


# --------------------------------------------------------------------------- #
# Baseline-agreement metrics (label-free)
# --------------------------------------------------------------------------- #

class TestOverlapAtK:
    def test_identical_top_k(self):
        assert overlap_at_k(["a", "b", "c"], ["a", "b", "z"], 2) == 1.0

    def test_disjoint_top_k(self):
        assert overlap_at_k(["a", "b"], ["x", "y"], 2) == 0.0

    def test_jaccard_partial(self):
        # top-2 sets {a,b} vs {b,c} → intersection 1, union 3.
        assert overlap_at_k(["a", "b"], ["b", "c"], 2) == 1 / 3

    def test_k_larger_than_lists(self):
        assert overlap_at_k(["a"], ["a"], 5) == 1.0


class TestKendallTau:
    def test_identical_order(self):
        assert kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_reversed_order(self):
        assert kendall_tau(["a", "b", "c"], ["c", "b", "a"]) == -1.0

    def test_single_swap(self):
        # one discordant pair out of three → (2-1)/3.
        tau = kendall_tau(["a", "b", "c"], ["b", "a", "c"])
        assert math.isclose(tau, 1 / 3)

    def test_only_common_items_considered(self):
        # "z" appears in only one list; tau is computed over the shared items.
        assert kendall_tau(["a", "b", "z"], ["a", "b"]) == 1.0

    def test_fewer_than_two_common_items(self):
        assert kendall_tau(["a"], ["a"]) == 0.0
        assert kendall_tau(["a"], ["b"]) == 0.0


# --------------------------------------------------------------------------- #
# Harness (injected embed seam)
# --------------------------------------------------------------------------- #

def _fake_embed(axis_by_word):
    """Build an embed seam that maps a text to a fixed vector per model.

    ``axis_by_word`` maps a model_id to a function text->vector. Lets tests make
    each model's geometry deterministic without any network.
    """

    def embed(model_id, texts):
        fn = axis_by_word[model_id]
        return [fn(t) for t in texts]

    return embed


class TestCompareModels:
    def _corpus(self):
        return [
            {"slug": "fed", "text": "the federal reserve raised rates"},
            {"slug": "btc", "text": "bitcoin is a bubble"},
            {"slug": "ecb", "text": "the european central bank eased"},
        ]

    def _queries(self):
        return [
            {"query": "what about the fed", "relevant_slugs": ["fed"]},
            {"query": "his view on bitcoin", "relevant_slugs": ["btc"]},
        ]

    def test_perfect_model_scores_top(self):
        # model "good": embeds each text onto a one-hot axis keyed by a keyword so
        # the matching query lands exactly on its relevant article.
        def good(text):
            t = text.lower()
            if "fed" in t or "federal" in t:
                return [1.0, 0.0, 0.0]
            if "bitcoin" in t:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        embed = _fake_embed({"good": good})
        records = compare_models(
            ["good"], self._corpus(), self._queries(), embed, ks=(1,)
        )
        assert len(records) == 1
        row = records[0]
        assert row["model"] == "good"
        assert row["retrieval"]["precision_at_1"] == 1.0
        assert row["retrieval"]["mrr"] == 1.0

    def test_agreement_vs_baseline(self):
        # Two models with identical geometry ⇒ identical rankings ⇒ full agreement.
        def good(text):
            t = text.lower()
            if "fed" in t or "federal" in t:
                return [1.0, 0.0, 0.0]
            if "bitcoin" in t:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        embed = _fake_embed({"good": good, "twin": good})
        records = compare_models(
            ["good", "twin"],
            self._corpus(),
            self._queries(),
            embed,
            baseline="good",
            ks=(1, 2),
        )
        twin = next(r for r in records if r["model"] == "twin")
        assert twin["agreement"]["mean_overlap_at_1"] == 1.0
        assert twin["agreement"]["mean_kendall_tau"] == 1.0
        # The baseline compared to itself is trivially perfect / omitted.
        good_row = next(r for r in records if r["model"] == "good")
        assert good_row["agreement"] is None or good_row["is_baseline"]

    def test_embed_called_once_per_model(self):
        calls = []

        def spy(model_id, texts):
            calls.append((model_id, len(texts)))
            return [[float(len(t)), 0.0] for t in texts]

        compare_models(["m1", "m2"], self._corpus(), self._queries(), spy, ks=(1,))
        models_called = {c[0] for c in calls}
        assert models_called == {"m1", "m2"}


class TestAggregateAndReport:
    def _records(self):
        return [
            {
                "model": "base",
                "is_baseline": True,
                "retrieval": {"precision_at_1": 1.0, "mrr": 1.0, "n_scored": 2},
                "agreement": None,
            },
            {
                "model": "cand",
                "is_baseline": False,
                "retrieval": {"precision_at_1": 0.5, "mrr": 0.75, "n_scored": 2},
                "agreement": {"mean_overlap_at_1": 0.5, "mean_kendall_tau": 0.2},
            },
        ]

    def test_aggregate_flags_best_and_baseline(self):
        summary = aggregate(self._records(), baseline="base")
        assert summary["baseline"] == "base"
        assert summary["n_models"] == 2
        # best by MRR is the baseline here.
        assert summary["best_mrr_model"] == "base"

    def test_write_report_roundtrips(self, tmp_path):
        out = tmp_path / "embedding_compare.json"
        summary = write_report(self._records(), out, baseline="base")
        payload = json.loads(out.read_text())
        assert payload["summary"] == summary
        assert len(payload["records"]) == 2
        assert "generated_at" in payload


class TestUnknownModels:
    def test_all_present(self):
        assert unknown_models(["a", "b"], ["a", "b", "c"]) == []

    def test_reports_missing_in_order(self):
        assert unknown_models(["x", "a", "y"], ["a"]) == ["x", "y"]

    def test_dedups_missing(self):
        assert unknown_models(["x", "x"], ["a"]) == ["x"]

    def test_empty_available(self):
        assert unknown_models(["a"], []) == ["a"]


class TestLoadQueries:
    def test_loads_queries_key(self, tmp_path):
        p = tmp_path / "q.json"
        p.write_text(json.dumps({"queries": [{"query": "x", "relevant_slugs": ["a"]}]}))
        qs = load_queries(p)
        assert qs == [{"query": "x", "relevant_slugs": ["a"]}]

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_queries(tmp_path / "nope.json") == []


class TestValidateQueries:
    corpus = {"a", "b", "c"}

    def test_clean_set_has_no_problems(self):
        qs = [
            {"query": "first?", "relevant_slugs": ["a"]},
            {"query": "second?", "relevant_slugs": ["b", "c"]},
        ]
        assert validate_queries(qs, self.corpus) == []

    def test_empty_set_is_a_problem(self):
        problems = validate_queries([], self.corpus)
        assert len(problems) == 1
        assert "no queries" in problems[0].lower()

    def test_unknown_slug_is_reported(self):
        qs = [{"query": "q?", "relevant_slugs": ["a", "ghost"]}]
        problems = validate_queries(qs, self.corpus)
        assert any("ghost" in p for p in problems)

    def test_blank_query_text_is_reported(self):
        qs = [{"query": "   ", "relevant_slugs": ["a"]}]
        problems = validate_queries(qs, self.corpus)
        assert any("query" in p.lower() and "empty" in p.lower() for p in problems)

    def test_empty_relevant_slugs_is_reported(self):
        qs = [{"query": "q?", "relevant_slugs": []}]
        problems = validate_queries(qs, self.corpus)
        assert any("relevant_slugs" in p for p in problems)

    def test_duplicate_slug_within_a_query_is_reported(self):
        qs = [{"query": "q?", "relevant_slugs": ["a", "a"]}]
        problems = validate_queries(qs, self.corpus)
        assert any("duplicate" in p.lower() for p in problems)

    def test_duplicate_query_text_is_reported(self):
        qs = [
            {"query": "same?", "relevant_slugs": ["a"]},
            {"query": "same?", "relevant_slugs": ["b"]},
        ]
        problems = validate_queries(qs, self.corpus)
        assert any("duplicate query" in p.lower() for p in problems)

    def test_problem_names_the_offending_index(self):
        qs = [
            {"query": "ok?", "relevant_slugs": ["a"]},
            {"query": "q?", "relevant_slugs": ["ghost"]},
        ]
        problems = validate_queries(qs, self.corpus)
        # the bad entry is index 1 (queries are 1-based in the message)
        assert any("2" in p for p in problems)


class TestLoadCorpusSlugs:
    def test_reads_slugs_from_manifest(self, tmp_path):
        m = tmp_path / "manifest.json"
        m.write_text(json.dumps({"articles": [{"slug": "a"}, {"slug": "b"}]}))
        assert load_corpus_slugs(m) == {"a", "b"}

    def test_skips_entries_without_a_slug(self, tmp_path):
        m = tmp_path / "manifest.json"
        m.write_text(json.dumps({"articles": [{"slug": "a"}, {"title": "no slug"}]}))
        assert load_corpus_slugs(m) == {"a"}


class TestCheckCLI:
    def _write(self, tmp_path, queries):
        q = tmp_path / "queries.json"
        q.write_text(json.dumps({"queries": queries}))
        m = tmp_path / "manifest.json"
        m.write_text(json.dumps({"articles": [{"slug": "a"}, {"slug": "b"}]}))
        return q, m

    def test_check_returns_0_on_valid_set(self, tmp_path, capsys):
        q, m = self._write(tmp_path, [{"query": "hi?", "relevant_slugs": ["a"]}])
        rc = main(["--check", "--queries", str(q), "--manifest", str(m)])
        assert rc == 0
        assert "OK" in capsys.readouterr().out

    def test_check_returns_1_and_lists_problems_on_invalid_set(self, tmp_path, capsys):
        q, m = self._write(tmp_path, [{"query": "hi?", "relevant_slugs": ["ghost"]}])
        rc = main(["--check", "--queries", str(q), "--manifest", str(m)])
        assert rc == 1
        assert "ghost" in capsys.readouterr().out

    def test_check_does_not_touch_the_conductor(self, tmp_path):
        # --check must run fully offline: no --models, no conductor reachability.
        q, m = self._write(tmp_path, [{"query": "hi?", "relevant_slugs": ["a"]}])
        assert main(["--check", "--queries", str(q), "--manifest", str(m)]) == 0


class TestCommittedGoldSet:
    """Guard: the checked-in eval/embedding_queries.json stays valid against the
    checked-in manifest, so a typo'd / renamed slug can't silently score 0."""

    def test_committed_gold_set_validates_against_committed_manifest(self):
        queries = load_queries()  # eval/embedding_queries.json
        corpus_slugs = load_corpus_slugs()  # data/manifest.json
        assert queries, "expected a non-empty committed gold query set"
        assert validate_queries(queries, corpus_slugs) == []


# --------------------------------------------------------------------------- #
# Per-query detail (#27) — a reviewer must be able to see *which* queries moved
# --------------------------------------------------------------------------- #

class TestPerQueryMetrics:
    def test_one_record_per_query_in_input_order(self):
        rankings = [["a", "b"], ["b", "a"], ["a", "b"]]
        relevants = [{"a"}, {"a"}, {"b"}]
        rows = per_query_metrics(rankings, relevants)
        assert len(rows) == 3

    def test_reports_reciprocal_rank_and_rank_of_first_hit(self):
        rankings = [["x", "y", "target"]]
        rows = per_query_metrics(rankings, [{"target"}])
        assert rows[0]["first_relevant_rank"] == 3
        assert rows[0]["reciprocal_rank"] == round(1 / 3, 4)

    def test_miss_reports_no_rank_and_zero_rr(self):
        rows = per_query_metrics([["x", "y"]], [{"absent"}])
        assert rows[0]["first_relevant_rank"] is None
        assert rows[0]["reciprocal_rank"] == 0.0

    def test_unlabelled_query_is_marked_unscored(self):
        rows = per_query_metrics([["x"]], [set()])
        assert rows[0]["scored"] is False
        assert rows[0]["n_relevant"] == 0

    def test_labelled_query_is_marked_scored(self):
        rows = per_query_metrics([["x"]], [{"x"}])
        assert rows[0]["scored"] is True
        assert rows[0]["n_relevant"] == 1

    def test_carries_query_text_when_given(self):
        rows = per_query_metrics([["x"]], [{"x"}], queries=[{"query": "the Fed"}])
        assert rows[0]["query"] == "the Fed"

    def test_query_text_absent_when_not_given(self):
        rows = per_query_metrics([["x"]], [{"x"}])
        assert rows[0]["query"] == ""


# --------------------------------------------------------------------------- #
# Paired comparison vs the baseline (#27) — is the MRR gap distinguishable
# from one query moving one rank slot?
# --------------------------------------------------------------------------- #

class TestPairedComparison:
    def test_counts_wins_losses_and_ties(self):
        out = paired_comparison([1.0, 0.5, 0.25], [0.5, 0.5, 1.0])
        assert (out["wins"], out["losses"], out["ties"]) == (1, 1, 1)

    def test_identical_rankings_are_all_ties(self):
        out = paired_comparison([1.0, 0.5], [1.0, 0.5])
        assert out["ties"] == 2
        assert out["wins"] == 0 and out["losses"] == 0

    def test_mean_delta_is_candidate_minus_baseline(self):
        out = paired_comparison([1.0, 1.0], [0.5, 0.0])
        assert out["mean_delta"] == 0.75

    def test_sign_test_p_is_the_exact_two_sided_binomial(self):
        # 5 wins, 0 losses -> 2 * (1/2**5)
        out = paired_comparison([1.0] * 5, [0.5] * 5)
        assert out["sign_test_p"] == round(2 / 32, 4)

    def test_sign_test_p_counts_only_non_tied_queries(self):
        # 5 wins, 0 losses, plus 3 ties -> the ties must not change p.
        out = paired_comparison([1.0] * 5 + [0.5] * 3, [0.5] * 5 + [0.5] * 3)
        assert out["sign_test_p"] == round(2 / 32, 4)

    def test_evenly_split_result_is_not_significant(self):
        out = paired_comparison([1.0, 0.5], [0.5, 1.0])
        assert out["sign_test_p"] == 1.0

    def test_reports_the_best_p_the_gold_set_could_ever_reach(self):
        # With 5 queries even a clean sweep only reaches 2/2**5 = 0.0625,
        # so *no* outcome on a 5-query gold set is significant at alpha=0.05.
        out = paired_comparison([1.0, 0.5, 0.5, 0.5, 0.5], [0.5] * 5)
        assert out["min_achievable_p"] == round(2 / 32, 4)

    def test_min_achievable_p_shrinks_as_the_gold_set_grows(self):
        out = paired_comparison([1.0] * 13, [0.5] * 13)
        assert out["min_achievable_p"] < 0.05

    def test_empty_input_is_inert(self):
        out = paired_comparison([], [])
        assert out["n"] == 0
        assert out["sign_test_p"] == 1.0
        assert out["mean_delta"] == 0.0


# --------------------------------------------------------------------------- #
# Margin-aware verdict (#27) — aggregate() must not crown a winner on noise
# --------------------------------------------------------------------------- #

class TestVerdict:
    def _rec(self, model, mrr_value, *, baseline=False, paired=None):
        return {
            "model": model,
            "is_baseline": baseline,
            "retrieval": {"mrr": mrr_value, "n_scored": 5},
            "agreement": None,
            "paired": paired,
        }

    # Built with the real paired_comparison() so these fixtures can't drift from
    # the shape compare_models() actually emits.
    _NARROW = paired_comparison(
        [1.0, 1.0, 0.5, 0.5, 0.25], [0.5, 0.5, 1.0, 0.5, 0.25]
    )  # 5 queries: 2 wins, 1 loss, 2 ties — the July run's shape
    _SWEEP = paired_comparison(
        [1.0] * 12 + [0.25], [0.5] * 12 + [1.0]
    )  # 13 queries: 12 wins, 1 loss
    _REVERSE_SWEEP = paired_comparison(
        [1.0] + [0.25] * 12, [0.5] + [1.0] * 12
    )  # 13 queries: 1 win, 12 losses

    def test_narrow_win_over_baseline_is_inconclusive(self):
        # cand leads on raw MRR, but the paired sign test can't distinguish it.
        records = [
            self._rec("base", 0.5286, baseline=True),
            self._rec("cand", 0.5556, paired=self._NARROW),
        ]
        summary = aggregate(records, baseline="base")
        assert summary["best_mrr_model"] == "cand"
        assert summary["verdict"] == "inconclusive"

    def test_clear_win_over_baseline_is_reported_as_better(self):
        records = [
            self._rec("base", 0.30, baseline=True),
            self._rec("cand", 0.90, paired=self._SWEEP),
        ]
        summary = aggregate(records, baseline="base")
        assert summary["verdict"] == "candidate_better"

    def test_baseline_winning_on_mrr_keeps_the_pin(self):
        records = [
            self._rec("base", 0.90, baseline=True),
            self._rec("cand", 0.30, paired=self._REVERSE_SWEEP),
        ]
        summary = aggregate(records, baseline="base")
        assert summary["verdict"] == "baseline_retained"

    def test_verdict_carries_a_human_reason(self):
        records = [
            self._rec("base", 0.5286, baseline=True),
            self._rec("cand", 0.5556, paired=self._NARROW),
        ]
        summary = aggregate(records, baseline="base")
        assert isinstance(summary["verdict_reason"], str)
        assert summary["verdict_reason"]

    def test_a_gold_set_too_small_to_decide_says_so(self):
        # 5 queries bottom out at p=0.0625, so the blame is the labels, not the model.
        records = [
            self._rec("base", 0.5286, baseline=True),
            self._rec("cand", 0.5556, paired=self._NARROW),
        ]
        summary = aggregate(records, baseline="base")
        assert "too small" in summary["verdict_reason"]

    def test_a_significant_p_with_a_negative_delta_is_not_a_win(self):
        # Guards the direction of the test: p alone must never crown a candidate.
        # cand edges ahead on mean MRR but lost 12 of 13 individual queries.
        records = [
            self._rec("base", 0.50, baseline=True),
            self._rec("cand", 0.5001, paired=self._REVERSE_SWEEP),
        ]
        summary = aggregate(records, baseline="base")
        assert summary["verdict"] == "inconclusive"


class TestCompareModelsAttachesEvidence:
    def _fake_embed(self):
        vectors = {
            "base": {"a": [1.0, 0.0], "b": [0.0, 1.0], "q": [1.0, 0.0]},
            "cand": {"a": [0.0, 1.0], "b": [1.0, 0.0], "q": [1.0, 0.0]},
        }

        def embed(model_id, texts):
            table = vectors[model_id]
            return [table[t] for t in texts]

        return embed

    def _corpus(self):
        return [{"slug": "a", "text": "a"}, {"slug": "b", "text": "b"}]

    def _queries(self):
        return [{"query": "q", "relevant_slugs": ["a"]}]

    def test_every_record_carries_per_query_detail(self):
        records = compare_models(
            ["base", "cand"], self._corpus(), self._queries(),
            self._fake_embed(), baseline="base",
        )
        assert all(len(r["per_query"]) == 1 for r in records)

    def test_baseline_record_has_no_paired_comparison(self):
        records = compare_models(
            ["base", "cand"], self._corpus(), self._queries(),
            self._fake_embed(), baseline="base",
        )
        assert records[0]["paired"] is None

    def test_candidate_record_is_paired_against_the_baseline(self):
        records = compare_models(
            ["base", "cand"], self._corpus(), self._queries(),
            self._fake_embed(), baseline="base",
        )
        # base ranks the relevant slug first, cand ranks it last -> one loss.
        assert records[1]["paired"]["losses"] == 1


class TestReportCarriesTheVerdict:
    def _records(self):
        return [
            {
                "model": "base", "is_baseline": True,
                "retrieval": {"mrr": 0.30, "n_scored": 13},
                "agreement": None, "per_query": [], "paired": None,
            },
            {
                "model": "cand", "is_baseline": False,
                "retrieval": {"mrr": 0.90, "n_scored": 13},
                "agreement": None, "per_query": [],
                "paired": paired_comparison([1.0] * 12 + [0.25], [0.5] * 12 + [1.0]),
            },
        ]

    def test_written_summary_includes_the_verdict(self, tmp_path):
        out = tmp_path / "r.json"
        write_report(self._records(), out, baseline="base")
        payload = json.loads(out.read_text())
        assert payload["summary"]["verdict"] == "candidate_better"

    def test_per_query_detail_survives_the_json_roundtrip(self, tmp_path):
        out = tmp_path / "r.json"
        records = self._records()
        records[0]["per_query"] = [
            {"query": "the Fed", "n_relevant": 1, "scored": True,
             "first_relevant_rank": 2, "reciprocal_rank": 0.5}
        ]
        write_report(records, out, baseline="base")
        payload = json.loads(out.read_text())
        assert payload["records"][0]["per_query"][0]["first_relevant_rank"] == 2

    def test_a_stricter_alpha_can_withhold_the_verdict(self, tmp_path):
        # p = 0.0034 for this 12-1 split: significant at 0.05, not at 0.001.
        out = tmp_path / "r.json"
        write_report(self._records(), out, baseline="base", alpha=0.001)
        payload = json.loads(out.read_text())
        assert payload["summary"]["verdict"] == "inconclusive"
