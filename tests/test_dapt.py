"""Tests for training/dapt.py — the DAPT (continued-pretraining) dataset (roadmap #54)."""

import json

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


# --- the preflight: refuse to stage a DAPT set that is not comparable ----------------------


def _chat(text: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Write."},
            {"role": "assistant", "content": text},
        ]
    }


SHARED = "his recurring line about the chip war that he used in two separate columns"
TRAIN_TEXT = "one two three four five six seven eight nine ten. " + SHARED
VALID_TEXT = "alpha beta gamma delta epsilon zeta eta theta iota kappa. " + SHARED


def _report(train=None, valid=None, instr_train=None, instr_heldout=None, max_seq_len=1024):
    return dapt.dapt_preflight(
        train if train is not None else [{"text": TRAIN_TEXT}],
        valid if valid is not None else [{"text": VALID_TEXT}],
        instr_train if instr_train is not None else [_chat(TRAIN_TEXT)],
        instr_heldout if instr_heldout is not None else [_chat(VALID_TEXT)],
        QLoRAConfig(max_seq_len=max_seq_len),
    )


class TestDaptPreflight:
    def test_a_faithful_set_passes(self):
        report = _report()
        assert report["ok"], dapt.render_dapt_report(report)

    def test_an_empty_text_record_fails_shape(self):
        report = _report(train=[{"text": TRAIN_TEXT}, {"text": "  "}])
        assert not report["checks"]["text_shape"]["ok"]

    def test_a_chat_record_fails_shape(self):
        """Staging the instruction records here by mistake would train the format back in."""
        assert not _report(train=[_chat(TRAIN_TEXT)])["checks"]["text_shape"]["ok"]

    def test_the_same_record_on_both_sides_fails_disjointness(self):
        report = _report(train=[{"text": TRAIN_TEXT}, {"text": VALID_TEXT}])
        assert not report["checks"]["split_disjoint"]["ok"]

    def test_a_record_over_the_window_fails_the_length_budget(self):
        assert not _report(max_seq_len=8)["checks"]["length_budget"]["ok"]

    def test_a_heldout_passage_on_the_train_side_fails_the_split_match(self):
        report = _report(train=[{"text": TRAIN_TEXT + "\n\n" + VALID_TEXT}])
        assert not report["checks"]["same_split"]["ok"]

    def test_an_instruction_passage_dapt_lacks_fails_the_split_match(self):
        """A stale ``make training`` (or a corpus edited since) breaks the comparison."""
        report = _report(instr_train=[_chat(TRAIN_TEXT), _chat("a passage dapt never saw")])
        assert not report["checks"]["same_split"]["ok"]

    def test_heldout_overlap_already_in_the_instruction_train_is_tolerated(self):
        """His own cross-article reuse (SHARED) is in both arms; DAPT adds nothing new."""
        check = _report()["checks"]["heldout_overlap"]
        assert check["ok"] and check["n_shared_with_instruction"] > 0

    def test_new_heldout_overlap_fails(self):
        leaky = TRAIN_TEXT + "\n\n" + "alpha beta gamma delta epsilon zeta eta theta iota"
        report = _report(train=[{"text": leaky}])
        assert not report["checks"]["heldout_overlap"]["ok"]

    def test_report_renders_every_check(self):
        text = dapt.render_dapt_report(_report())
        for name in ("text shape", "split disjoint", "length budget", "same split", "heldout"):
            assert name in text


class TestStageDaptData:
    def test_stages_text_only_train_and_valid(self, tmp_path, monkeypatch):
        from training.finetune_config import load_jsonl

        data, questions = _write_corpus(tmp_path, monkeypatch)
        out = tmp_path / "run" / "dapt"
        counts = dapt.stage_dapt_data(data / "training", data, questions, out_dir=out)
        train, valid = load_jsonl(out / "train.jsonl"), load_jsonl(out / "valid.jsonl")
        assert counts["preflight_ok"]
        assert (counts["n_train"], counts["n_valid"]) == (len(train), len(valid))
        assert train and valid and all(set(r) == {"text"} for r in train + valid)

    def test_refuses_and_writes_nothing_when_the_preflight_fails(self, tmp_path, monkeypatch):
        import pytest

        from training.finetune_preflight import PreflightError

        data, questions = _write_corpus(tmp_path, monkeypatch)
        with open(data / "training" / "train.jsonl", "a") as f:  # a stale instruction set
            f.write(json.dumps(_chat("text from a corpus that no longer exists")) + "\n")
        out = tmp_path / "run" / "dapt"
        with pytest.raises(PreflightError, match="same split"):
            dapt.stage_dapt_data(data / "training", data, questions, out_dir=out)
        assert not out.exists()

    def test_force_stages_past_a_failing_preflight(self, tmp_path, monkeypatch):
        data, questions = _write_corpus(tmp_path, monkeypatch)
        with open(data / "training" / "train.jsonl", "a") as f:
            f.write(json.dumps(_chat("text from a corpus that no longer exists")) + "\n")
        out = tmp_path / "run" / "dapt"
        counts = dapt.stage_dapt_data(data / "training", data, questions, out_dir=out, force=True)
        assert not counts["preflight_ok"] and (out / "train.jsonl").exists()

    def test_never_writes_into_the_instruction_run_dir(self):
        """mlx-lm --data reads a whole directory; the two objectives must not share one."""
        from training.finetune_config import FINETUNE_DIR

        assert dapt.DAPT_DIR != FINETUNE_DIR and dapt.DAPT_DIR.parent == FINETUNE_DIR


def test_make_dapt_prep_runs_this_module_with_args():
    """The README and module docstring tell a human to run `make dapt-prep`."""
    from pathlib import Path

    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "\ndapt-prep:" in makefile
    recipe = makefile.split("\ndapt-prep:", 1)[1].split("\n\n", 1)[0]
    assert "training.dapt" in recipe and "$(ARGS)" in recipe
