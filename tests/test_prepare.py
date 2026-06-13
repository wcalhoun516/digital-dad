"""Tests for training/prepare.py — the Geo LLM dataset builder (plan 0008, step 26a).

Exercises the pure shaping/splitting logic on small fixtures (no corpus, no
conductor): instruction-record shaping, the #25-eval-overlap mapping, and the
deterministic train/held-out partition.
"""

from training.prepare import (
    build_instruct_record,
    eval_grounded_slugs,
    split_articles,
)


class TestBuildInstructRecord:
    def test_has_system_user_assistant_messages(self):
        rec = build_instruct_record("Why The Fed Prints Alpha", "The body.")
        roles = [m["role"] for m in rec["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_user_prompt_derives_topic_from_title(self):
        # leading "Why" + trailing "?" are stripped by _article_to_topic
        rec = build_instruct_record("Why Is Inflation Real?", "Body text here.")
        assert rec["messages"][1]["content"] == "Write an analysis of Is Inflation Real."

    def test_assistant_content_is_the_body(self):
        rec = build_instruct_record("Some Title", "The full article body.")
        assert rec["messages"][2]["content"] == "The full article body."


class TestEvalGroundedSlugs:
    def _articles(self):
        return [
            {"slug": "inflation-still-exist", "title": "Does Inflation Still Exist?"},
            {
                "slug": "fed-prints-alpha",
                "title": "The Fed Doesn’t Just Print Money, It Also Prints Alpha",
            },
            {"slug": "unrelated-piece", "title": "A Totally Different Subject"},
        ]

    def test_matches_article_whose_title_appears_in_a_topic_hint(self):
        questions = [{"question": "Does inflation still exist?", "topic_hint": "Does Inflation Still Exist? (2020)"}]  # noqa: E501
        assert eval_grounded_slugs(questions, self._articles()) == {"inflation-still-exist"}

    def test_leaves_unreferenced_articles_out(self):
        questions = [{"question": "Does inflation still exist?", "topic_hint": "Does Inflation Still Exist? (2020)"}]  # noqa: E501
        assert "unrelated-piece" not in eval_grounded_slugs(questions, self._articles())

    def test_robust_to_typographic_punctuation(self):
        # article title carries a curly apostrophe; the hint uses a straight one
        hint = "The Fed Doesn't Just Print Money, It Also Prints Alpha (2020)"
        questions = [{"question": "Fed alpha?", "topic_hint": hint}]
        assert "fed-prints-alpha" in eval_grounded_slugs(questions, self._articles())

    def test_no_questions_yields_empty_set(self):
        assert eval_grounded_slugs([], self._articles()) == set()


class TestSplitArticles:
    def test_excluded_slugs_land_in_neither_split(self):
        slugs = ["a", "b", "c", "d"]
        train, heldout = split_articles(slugs, excluded={"b"})
        assert "b" not in train
        assert "b" not in heldout

    def test_partition_is_deterministic(self):
        slugs = [f"slug-{i}" for i in range(50)]
        first = split_articles(slugs)
        second = split_articles(slugs)
        assert first == second

    def test_train_and_heldout_are_disjoint_and_cover_remaining(self):
        slugs = [f"slug-{i}" for i in range(50)]
        excluded = {"slug-0", "slug-1"}
        train, heldout = split_articles(slugs, excluded=excluded)
        assert set(train).isdisjoint(heldout)
        assert set(train) | set(heldout) == set(slugs) - excluded

    def test_zero_fraction_puts_everything_in_train(self):
        slugs = [f"slug-{i}" for i in range(20)]
        train, heldout = split_articles(slugs, heldout_frac=0.0)
        assert heldout == []
        assert set(train) == set(slugs)

    def test_heldout_excludes_eval_grounded_slugs(self):
        articles = [
            {"slug": "inflation-still-exist", "title": "Does Inflation Still Exist?"},
            {"slug": "other-1", "title": "Some Other Piece One"},
            {"slug": "other-2", "title": "Some Other Piece Two"},
        ]
        questions = [{"question": "q", "topic_hint": "Does Inflation Still Exist? (2020)"}]
        excluded = eval_grounded_slugs(questions, articles)
        train, heldout = split_articles([a["slug"] for a in articles], excluded=excluded)
        assert "inflation-still-exist" not in heldout
        assert "inflation-still-exist" not in train
