"""Tests for training/prepare.py — the Geo LLM dataset builder (plan 0008, step 26a).

Exercises the pure shaping/splitting logic on small fixtures (no corpus, no
conductor): instruction-record shaping, the #25-eval-overlap mapping, and the
deterministic train/held-out partition.
"""

import json

from training import prepare
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


class TestRunDeduplicatesTheCorpus:
    """`run()` walks the manifest directly, so it inherits the duplicate-slug defect:
    23 articles appear twice in data/manifest.json, and each was written to
    finetune.jsonl/instruct.jsonl twice — silently over-weighting them in the QLoRA run.
    """

    def _corpus(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw"
        raw.mkdir()
        body = "Sentence about the economy. " * 200  # clears the 400-word quality bar
        for name in ("dup", "solo"):
            (raw / f"{name}.json").write_text(
                json.dumps({"title": f"Title {name}", "body": body, "date": "2021-01-01"})
            )
        entries = [
            {"slug": "dup", "url": "http://f.com/dup/", "file": "raw/dup.json",
             "title": "Title dup", "date": "2021-01-01", "word_count": 1000},
            {"slug": "dup", "url": "https://f.com/dup/", "file": "raw/dup.json",
             "title": "Title dup", "date": "2021-01-01", "word_count": 1000},
            {"slug": "solo", "url": "https://f.com/solo/", "file": "raw/solo.json",
             "title": "Title solo", "date": "2021-01-02", "word_count": 1000},
        ]
        (tmp_path / "manifest.json").write_text(
            json.dumps({"total_articles": len(entries), "articles": entries})
        )
        monkeypatch.setattr(prepare, "DATA_DIR", tmp_path)
        monkeypatch.setattr(prepare, "MANIFEST_PATH", tmp_path / "manifest.json")
        monkeypatch.setattr(prepare, "TRAINING_DIR", tmp_path / "training")
        monkeypatch.setattr(prepare, "LINGUISTICS_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(prepare, "EVAL_QUESTIONS_PATH", tmp_path / "absent.json")
        return tmp_path / "training"

    def test_finetune_jsonl_has_one_line_per_article(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        lines = (out / "finetune.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_instruct_jsonl_has_one_line_per_article(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        lines = (out / "instruct.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_the_duplicated_article_body_appears_once(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        records = [json.loads(x) for x in (out / "finetune.jsonl").read_text().splitlines()]
        assert sum(1 for r in records if "Sentence about the economy" in r["text"]) == 2
