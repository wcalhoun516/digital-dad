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
    load_queries,
    mrr,
    overlap_at_k,
    precision_at_k,
    rank_slugs,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
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


class TestLoadQueries:
    def test_loads_queries_key(self, tmp_path):
        p = tmp_path / "q.json"
        p.write_text(json.dumps({"queries": [{"query": "x", "relevant_slugs": ["a"]}]}))
        qs = load_queries(p)
        assert qs == [{"query": "x", "relevant_slugs": ["a"]}]

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_queries(tmp_path / "nope.json") == []
