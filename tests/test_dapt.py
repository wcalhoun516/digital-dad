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
