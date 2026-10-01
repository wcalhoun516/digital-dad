"""Positions index (roadmap #43): what he held to be true, grouped by subject, with his record.

``predictions.json`` holds 611 dated, adjudicated claims spread across ~400 free-text topic
strings — the doctrine is present and scored, but not grouped, so nothing can answer "what
did he say about the Fed, and how did it go?". These tests pin the grouping against a fake
embedder whose vectors are chosen by hand, so every cluster boundary is asserted exactly.

Three judgements are pinned here:

**A topic string is never split.** The clustering unit is the canonical topic, not the
claim, so two claims filed under "Fed policy" always land in the same subject even when their
texts point different ways. ``aliases`` lists topics; a topic in two subjects would make that
list a lie.

**Average linkage, not single linkage.** Single linkage chains: A≈B and B≈C merges A with C
even when A and C have nothing in common, and on 400 overlapping topic strings that collapses
half the archive into one blob.

**The record goes through ``adjudicate.effective_verdict``.** A ruling from ``make
adjudicate`` must outrank the advisory LLM verdict here exactly as it does on the Track
Record tab, or the two surfaces would disagree about the same claim.
"""

import json
import math

import pytest

from analysis.positions import (
    DEFAULT_THRESHOLD,
    build_document,
    build_positions,
    cluster,
)
from analysis.utils import DATA_DIR

# The hand-built geometry. Keys are lowercased topics; a claim's embedded text starts with its
# topic, so the fake resolves claim texts to the same vector as their topic.
FED = (1.0, 0.0, 0.0)
OIL = (0.0, 1.0, 0.0)
EGGS = (0.0, 0.0, 1.0)


def fake_embed(table):
    """An ``embed`` seam that looks each text's topic up in ``table`` and counts its calls."""

    def embed(texts):
        embed.calls += 1
        return [list(table[text.split(":")[0].strip().lower()]) for text in texts]

    embed.calls = 0
    return embed


def prediction(topic, claim="He said so.", date="2021-01-01", **verdicts):
    return {
        "claim": claim,
        "topic": topic,
        "prediction_date": date,
        "article_date": date,
        "article_slug": f"slug-{topic.lower().replace(' ', '-')}-{date}",
        "article_title": f"On {topic}",
        "article_url": f"https://example.com/{date}",
        "confidence_language": "confident",
        **verdicts,
    }


class TestGrouping:
    def test_similar_topics_fold_into_one_subject(self):
        preds = [prediction("Fed policy"), prediction("FOMC"), prediction("oil prices")]
        embed = fake_embed({"fed policy": FED, "fomc": FED, "oil prices": OIL})

        subjects = build_positions(preds, embed=embed)

        assert sorted(sorted(s["aliases"]) for s in subjects) == [
            ["FOMC", "Fed policy"],
            ["oil prices"],
        ]

    def test_case_and_alias_variants_of_one_topic_are_one_topic(self):
        # entity_aliases.canonicalize does the cheap folding before anything is embedded.
        preds = [prediction("The Fed"), prediction("Fed"), prediction("federal reserve")]
        embed = fake_embed({"federal reserve": FED})

        (subject,) = build_positions(preds, embed=embed)

        assert len(subject["claims"]) == 3

    def test_a_topic_is_never_split_across_subjects(self):
        # The two claims' texts point at orthogonal vectors, but they share a topic string.
        preds = [
            prediction("Fed policy", claim="oil: about oil really"),
            prediction("Fed policy", claim="eggs: about eggs really"),
        ]
        table = {"fed policy": FED}

        def embed(texts):
            # Topic texts embed to FED; claim texts embed by the word after the topic prefix.
            out = []
            for text in texts:
                head, _, rest = text.partition(":")
                word = rest.strip().split(":")[0].strip().lower()
                out.append(list({"oil": OIL, "eggs": EGGS}.get(word, table[head.strip().lower()])))
            return out

        (subject,) = build_positions(preds, embed=embed)

        assert len(subject["claims"]) == 2

    # The blend was measured on the real corpus (see the module docstring): each signal alone
    # made one of these two mistakes. The fake below embeds a bare topic by its own name and a
    # "topic: claim" text by its claim, so the two signals can be set independently.
    @staticmethod
    def split_embed(topics, claims):
        def embed(texts):
            return [
                list(claims[text.split(":", 1)[1].strip()] if ":" in text else topics[text])
                for text in texts
            ]

        return embed

    def test_a_shared_word_in_the_topic_alone_does_not_merge(self):
        # "Tesla valuation" vs "Alibaba valuation": the topic strings embed alike, what he
        # actually said about each does not. Topic-only embedding merged these.
        preds = [
            prediction("Tesla valuation", claim="cars"),
            prediction("Alibaba valuation", claim="china"),
        ]
        embed = self.split_embed(
            {"Tesla valuation": FED, "Alibaba valuation": FED},
            {"cars": OIL, "china": EGGS},
        )

        assert len(build_positions(preds, embed=embed)) == 2

    def test_claims_discussed_together_do_not_merge_distinct_topics(self):
        # "stock market" vs "Fed policy": he writes about them in the same breath, so the
        # claims embed alike, but they are different subjects. Claims-only embedding merged these.
        preds = [
            prediction("stock market", claim="rates and stocks"),
            prediction("Fed policy", claim="rates and stocks too"),
        ]
        embed = self.split_embed(
            {"stock market": OIL, "Fed policy": EGGS},
            {"rates and stocks": FED, "rates and stocks too": FED},
        )

        assert len(build_positions(preds, embed=embed)) == 2

    def test_topics_alike_in_name_and_substance_merge(self):
        preds = [
            prediction("EU fiscal union", claim="bonds"),
            prediction("EU fiscal integration", claim="joint bonds"),
        ]
        embed = self.split_embed(
            {"EU fiscal union": FED, "EU fiscal integration": FED},
            {"bonds": OIL, "joint bonds": OIL},
        )

        assert len(build_positions(preds, embed=embed)) == 1

    def test_unrelated_topics_stay_apart(self):
        preds = [prediction("Fed policy"), prediction("egg prices")]
        embed = fake_embed({"fed policy": FED, "egg prices": EGGS})

        assert len(build_positions(preds, embed=embed)) == 2

    def test_blank_topics_are_left_out_rather_than_grouped(self):
        preds = [prediction("Fed policy"), prediction("  ")]
        embed = fake_embed({"fed policy": FED})

        (subject,) = build_positions(preds, embed=embed)

        assert len(subject["claims"]) == 1

    def test_no_predictions_means_no_subjects_and_no_embedding_call(self):
        embed = fake_embed({})

        assert build_positions([], embed=embed) == []
        assert embed.calls == 0


class TestCluster:
    def test_threshold_is_inclusive(self):
        # cos(a, b) == 0.6 exactly.
        vectors = [[1.0, 0.0], [0.6, 0.8]]

        assert cluster(vectors, threshold=0.6) == [[0, 1]]
        assert cluster(vectors, threshold=0.61) == [[0], [1]]

    def test_average_linkage_does_not_chain(self):
        # a~b = 0.7 and b~c ≈ 0.714, but a~c = 0. Single linkage would merge all three.
        a = [1.0, 0.0]
        b = [0.7, math.sqrt(1 - 0.49)]
        c = [0.0, 1.0]

        assert cluster([a, b, c], threshold=0.6) == [[0], [1, 2]]

    def test_unnormalized_vectors_are_compared_by_cosine(self):
        # Parallel, so cosine 1.0 — but a raw dot product of 0.02 would never merge them.
        assert cluster([[0.1, 0.0], [0.2, 0.0]], threshold=0.99) == [[0, 1]]

    def test_output_is_deterministic_and_ordered_by_first_member(self):
        vectors = [list(EGGS), list(FED), list(EGGS), list(FED)]

        assert cluster(vectors, threshold=0.9) == [[0, 2], [1, 3]]


class TestSubjectRecord:
    def test_record_resolves_through_effective_verdict(self):
        preds = [
            # A human ruling outranks the advisory LLM guess.
            prediction("Fed policy", llm_verdict="wrong", human_verdict="vindicated"),
            prediction("Fed policy", llm_verdict="wrong"),
            prediction("Fed policy", evidence_verdict="mixed", llm_verdict="vindicated"),
            prediction("Fed policy"),
        ]
        embed = fake_embed({"fed policy": FED})

        (subject,) = build_positions(preds, embed=embed)

        assert subject["record"] == {
            "vindicated": 1,
            "wrong": 1,
            "mixed": 1,
            "unfalsifiable": 0,
            "pending": 1,
        }
        assert [c["verdict"] for c in subject["claims"]].count("vindicated") == 1

    def test_claims_are_dated_sourced_and_in_date_order(self):
        preds = [
            prediction("Fed policy", claim="Later.", date="2023-03-11", llm_verdict="wrong"),
            prediction("Fed policy", claim="Earlier.", date="2020-04-13"),
        ]
        embed = fake_embed({"fed policy": FED})

        (subject,) = build_positions(preds, embed=embed)

        assert [c["claim"] for c in subject["claims"]] == ["Earlier.", "Later."]
        assert subject["span"] == ["2020-04-13", "2023-03-11"]
        later = subject["claims"][1]
        assert later["date"] == "2023-03-11"
        assert later["slug"] == "slug-fed-policy-2023-03-11"
        assert later["title"] == "On Fed policy"
        assert later["url"] == "https://example.com/2023-03-11"
        assert later["confidence_language"] == "confident"
        assert later["verdict"] == "wrong"
        assert later["verdict_source"] == "llm"

    def test_missing_prediction_date_falls_back_to_the_article_date(self):
        pred = prediction("Fed policy", date="2021-06-01")
        del pred["prediction_date"]
        embed = fake_embed({"fed policy": FED})

        (subject,) = build_positions([pred], embed=embed)

        assert subject["claims"][0]["date"] == "2021-06-01"

    def test_subject_is_named_after_its_most_used_topic(self):
        preds = [
            prediction("FOMC"),
            prediction("Fed policy"),
            prediction("Fed policy", date="2022-01-01"),
        ]
        embed = fake_embed({"fed policy": FED, "fomc": FED})

        (subject,) = build_positions(preds, embed=embed)

        assert subject["subject"] == "Fed policy"
        assert subject["id"] == "pos:fed-policy"
        assert subject["aliases"] == ["Fed policy", "FOMC"]

    def test_ids_stay_unique_when_names_slug_alike(self):
        preds = [prediction("Fed policy"), prediction("Fed-policy!")]
        embed = fake_embed({"fed policy": FED, "fed-policy!": OIL})

        ids = [s["id"] for s in build_positions(preds, embed=embed)]

        assert len(set(ids)) == 2
        assert set(ids) == {"pos:fed-policy", "pos:fed-policy-2"}

    def test_subjects_are_ordered_by_depth(self):
        preds = [
            prediction("egg prices"),
            prediction("Fed policy"),
            prediction("Fed policy", date="2022-01-01"),
        ]
        embed = fake_embed({"fed policy": FED, "egg prices": EGGS})

        subjects = build_positions(preds, embed=embed)

        assert [s["subject"] for s in subjects] == ["Fed policy", "egg prices"]


class TestDocument:
    def test_meta_records_how_the_grouping_was_made(self):
        preds = [prediction("Fed policy"), prediction("FOMC"), prediction("  ")]
        embed = fake_embed({"fed policy": FED, "fomc": FED})

        doc = build_document(preds, embed=embed, embed_model="fake-model")

        assert doc["meta"]["embed_model"] == "fake-model"
        assert doc["meta"]["threshold"] == DEFAULT_THRESHOLD
        assert doc["meta"]["num_predictions"] == 3
        assert doc["meta"]["untopiced"] == 1
        assert doc["meta"]["num_topics"] == 2
        assert doc["meta"]["num_subjects"] == 1
        assert len(doc["subjects"]) == 1


# ---------------------------------------------------------------------------
# Real-corpus guard — invariants of the shipped artifact, not frozen numbers, so a re-run
# after re-adjudication does not make it brittle. Skips on a fresh clone.
# ---------------------------------------------------------------------------

POSITIONS_PATH = DATA_DIR / "analysis" / "positions.json"
PREDICTIONS_PATH = DATA_DIR / "analysis" / "predictions.json"


@pytest.mark.skipif(
    not (POSITIONS_PATH.exists() and PREDICTIONS_PATH.exists()),
    reason="positions.json not built",
)
class TestShippedPositions:
    @pytest.fixture(scope="class")
    def doc(self):
        return json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))

    def test_every_topiced_prediction_appears_exactly_once(self, doc):
        claims = sum(len(s["claims"]) for s in doc["subjects"])
        assert claims == doc["meta"]["num_predictions"] - doc["meta"]["untopiced"]

    def test_each_record_tallies_its_own_claims(self, doc):
        for s in doc["subjects"]:
            assert sum(s["record"].values()) == len(s["claims"]), s["id"]
            assert s["span"] == [s["claims"][0]["date"], s["claims"][-1]["date"]], s["id"]

    def test_no_topic_is_filed_under_two_subjects(self, doc):
        seen = [alias.casefold() for s in doc["subjects"] for alias in s["aliases"]]
        assert len(seen) == len(set(seen))

    def test_ids_are_unique(self, doc):
        ids = [s["id"] for s in doc["subjects"]]
        assert len(ids) == len(set(ids))
