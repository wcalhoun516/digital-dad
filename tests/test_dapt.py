"""Tests for training/dapt.py — the DAPT (continued-pretraining) dataset (roadmap #54)."""

from training import dapt
from training.finetune_config import QLoRAConfig
from training.prepare import build_passage_records

PARAS = [f"Paragraph {i} makes one point. It then makes a second point." for i in range(40)]
BODY = "\n\n".join(PARAS)


class TestBudget:
    def test_budget_follows_the_run_window(self):
        assert dapt.dapt_budget_chars(QLoRAConfig(max_seq_len=2048)) == 2 * dapt.dapt_budget_chars(
            QLoRAConfig(max_seq_len=1024)
        )


class TestBuildDaptRecords:
    def test_records_are_plain_text_with_no_prompt(self):
        records = dapt.build_dapt_records(BODY, max_chars=500)
        assert records and all(set(r) == {"text"} for r in records)

    def test_no_record_exceeds_the_budget(self):
        assert all(len(r["text"]) <= 500 for r in dapt.build_dapt_records(BODY, max_chars=500))

    def test_the_whole_body_reaches_the_model_exactly_once(self):
        records = dapt.build_dapt_records(BODY, max_chars=500)
        rejoined = "\n\n".join(r["text"] for r in records)
        assert rejoined.split("\n\n") == PARAS

    def test_blank_body_yields_no_records(self):
        assert dapt.build_dapt_records("   \n\n ", max_chars=500) == []

    def test_carries_more_prose_per_record_than_a_chat_passage(self):
        """No system prompt or user turn to pay for, so the same window holds more of him."""
        budget, long_body = dapt.dapt_budget_chars(), "\n\n".join(PARAS * 10)
        assert len(dapt.build_dapt_records(long_body, budget)) < len(
            build_passage_records("A title", long_body, slug="s", max_chars=budget)
        )


# --- the split: DAPT must train on exactly the instruction set's articles --------------

FOOTER = "George Calhoun writes about technology and finance. Follow him on LinkedIn."
HELDOUT = {"article-1", "article-7"}  # where split_articles buckets these slugs
SHORT = "article-3"  # under 400 words -> filtered by the quality rule
GROUNDED = "article-5"  # an eval question is grounded in it -> reserved out of both


def _title(i: int) -> str:
    return f"Title number {i} about semiconductor policy"


def _body(i: int) -> str:
    n_paras = 2 if f"article-{i}" == SHORT else 10
    paras = [" ".join(f"a{i}p{p}w{w}" for w in range(50)) + "." for p in range(n_paras)]
    return "\n\n".join(paras + [FOOTER])


def _write_corpus(root, monkeypatch, n=12):
    """A tiny corpus, run through the real ``prepare.run()`` the way ``make training`` does."""
    import json

    from training import prepare

    data = root / "data"
    (data / "raw").mkdir(parents=True)
    entries = []
    for i in range(n):
        slug = f"article-{i}"
        body = _body(i)
        (data / "raw" / f"{slug}.json").write_text(
            json.dumps({"title": _title(i), "body": body, "date": f"2024-01-{i + 1:02d}"})
        )
        entries.append(
            {
                "slug": slug,
                "title": _title(i),
                "date": f"2024-01-{i + 1:02d}",
                "file": f"raw/{slug}.json",
                "word_count": len(body.split()),
                "url": f"https://example.com/{slug}",
            }
        )
    (data / "manifest.json").write_text(json.dumps({"articles": entries}))
    questions = root / "questions.json"
    questions.write_text(
        json.dumps({"questions": [{"question": "What did he say?", "topic_hint": _title(5)}]})
    )
    for name, value in {
        "DATA_DIR": data,
        "RAW_DIR": data / "raw",
        "TRAINING_DIR": data / "training",
        "MANIFEST_PATH": data / "manifest.json",
        "LINGUISTICS_PATH": data / "analysis" / "linguistics.json",
        "EVAL_QUESTIONS_PATH": questions,
    }.items():
        monkeypatch.setattr(prepare, name, value)
    prepare.run()
    return data, questions


def _article_ids(records) -> set[str]:
    """Which fixture articles a set of records carries prose from (``a<i>p`` tokens)."""
    import re

    text = " ".join(r["text"] for r in records)
    return {f"article-{i}" for i in re.findall(r"\ba(\d+)p\d+w\d+\b", text)}


class TestLoadDaptSplit:
    def test_train_is_exactly_the_instruction_train_articles(self, tmp_path, monkeypatch):
        data, questions = _write_corpus(tmp_path, monkeypatch)
        split = dapt.load_dapt_split(data / "training", data, questions)
        expected = {f"article-{i}" for i in range(12)} - HELDOUT - {SHORT, GROUNDED}
        assert _article_ids(split["train"]) == expected

    def test_valid_is_exactly_the_heldout_articles(self, tmp_path, monkeypatch):
        data, questions = _write_corpus(tmp_path, monkeypatch)
        split = dapt.load_dapt_split(data / "training", data, questions)
        assert _article_ids(split["valid"]) == HELDOUT

    def test_every_instruction_passage_is_on_the_same_side(self, tmp_path, monkeypatch):
        """The coupling to ``prepare`` itself, not to this test's idea of it."""
        from training.finetune_config import load_jsonl
        from training.finetune_preflight import assistant_content

        data, questions = _write_corpus(tmp_path, monkeypatch)
        split = dapt.load_dapt_split(data / "training", data, questions)
        for side, src in (("train", "train.jsonl"), ("valid", "heldout.jsonl")):
            prose = "\n\n".join(r["text"] for r in split[side])
            for record in load_jsonl(data / "training" / src):
                assert assistant_content(record) in prose

    def test_the_cross_article_footer_is_stripped(self, tmp_path, monkeypatch):
        data, questions = _write_corpus(tmp_path, monkeypatch)
        split = dapt.load_dapt_split(data / "training", data, questions)
        assert not any(FOOTER in r["text"] for r in split["train"] + split["valid"])

    def test_missing_metadata_says_to_run_make_training(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError, match="make training"):
            dapt.load_dapt_split(tmp_path / "training", tmp_path, tmp_path / "q.json")
