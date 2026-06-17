"""Tests for training/finetune_preflight.py — the QLoRA pre-flight checks
(plan 0008, de-risks step 26c).

Pure, offline checks over 26a's leakage-free split: chat-shape integrity,
train/held-out disjointness, and the sequence-length budget vs the run config's
``max_seq_len``. No MLX, no model download, no conductor.
"""

import json

import pytest

from training.finetune_config import QLoRAConfig
from training.finetune_preflight import (
    assistant_content,
    chat_shape_errors,
    check_chat_shape,
    check_length_budget,
    check_split_disjoint,
    load_split,
    preflight,
    render_report,
    run,
)


def _rec(topic: str, body: str = "Some analysis body that is reasonably long enough.") -> dict:
    return {
        "messages": [
            {"role": "system", "content": "You are Dr. George Calhoun."},
            {"role": "user", "content": f"Write an analysis of {topic}."},
            {"role": "assistant", "content": body},
        ]
    }


class TestAssistantContent:
    def test_returns_assistant_turn(self):
        assert assistant_content(_rec("A", body="hello")) == "hello"

    def test_none_when_absent(self):
        rec = {"messages": [{"role": "user", "content": "hi"}]}
        assert assistant_content(rec) is None


class TestChatShapeErrors:
    def test_wellformed_record_has_no_errors(self):
        assert chat_shape_errors(_rec("A")) == []

    def test_flags_missing_role(self):
        rec = {
            "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
        }
        errors = chat_shape_errors(rec)
        assert any("system" in e for e in errors)

    def test_flags_empty_assistant_content(self):
        rec = _rec("A", body="   ")
        errors = chat_shape_errors(rec)
        assert any("assistant" in e for e in errors)

    def test_flags_no_messages(self):
        assert chat_shape_errors({}) != []


class TestCheckChatShape:
    def test_all_wellformed_is_ok(self):
        result = check_chat_shape([_rec("A"), _rec("B")])
        assert result["ok"] is True
        assert result["n"] == 2
        assert result["n_malformed"] == 0

    def test_reports_malformed_with_index(self):
        bad = {"messages": [{"role": "user", "content": "hi"}]}
        result = check_chat_shape([_rec("A"), bad])
        assert result["ok"] is False
        assert result["n_malformed"] == 1
        # the issue list should point at the offending record index
        assert any(issue["index"] == 1 for issue in result["issues"])


class TestCheckSplitDisjoint:
    def test_disjoint_splits_are_ok(self):
        train = [_rec("A", body="aaa"), _rec("B", body="bbb")]
        valid = [_rec("C", body="ccc")]
        result = check_split_disjoint(train, valid)
        assert result["ok"] is True
        assert result["n_overlap"] == 0

    def test_detects_leaked_record_by_assistant_content(self):
        leaked = _rec("A", body="identical body text")
        # same assistant body appears in both splits even if the prompt differs
        valid_dup = _rec("A-renamed", body="identical body text")
        result = check_split_disjoint([leaked, _rec("B", body="bbb")], [valid_dup])
        assert result["ok"] is False
        assert result["n_overlap"] == 1

    def test_overlap_examples_are_capped_and_deterministic(self):
        train = [_rec(f"t{i}", body=f"dup-{i}") for i in range(10)]
        valid = [_rec(f"v{i}", body=f"dup-{i}") for i in range(10)]
        result = check_split_disjoint(train, valid)
        assert result["n_overlap"] == 10
        assert result["examples"] == check_split_disjoint(train, valid)["examples"]
        assert len(result["examples"]) <= 5


class TestCheckLengthBudget:
    def test_short_records_under_budget_are_ok(self):
        recs = [_rec("A", body="short body"), _rec("B", body="also short")]
        result = check_length_budget(recs, max_seq_len=1024, chars_per_token=4)
        assert result["ok"] is True
        assert result["n_over"] == 0
        assert result["max_seq_len"] == 1024

    def test_flags_records_exceeding_max_seq_len(self):
        long_body = "word " * 6000  # ~30k chars -> ~7500 est tokens at chars/4
        recs = [_rec("A", body="short"), _rec("B", body=long_body)]
        result = check_length_budget(recs, max_seq_len=1024, chars_per_token=4)
        assert result["ok"] is False
        assert result["n_over"] == 1
        assert result["pct_over"] == 50.0
        assert result["max_est_tokens"] >= result["median_est_tokens"]

    def test_empty_records_is_safe(self):
        result = check_length_budget([], max_seq_len=1024)
        assert result["ok"] is True
        assert result["n"] == 0
        assert result["suggested_max_seq_len"] is None

    def test_suggests_a_power_of_two_seq_len_covering_p95(self):
        # 95 short + 5 long records: P95 is short, so the suggestion stays modest
        # and is a clean power of two that covers it.
        recs = [_rec(f"s{i}", body="word " * 50) for i in range(95)]
        recs += [_rec(f"l{i}", body="word " * 6000) for i in range(5)]
        result = check_length_budget(recs, max_seq_len=128, chars_per_token=4)
        sug = result["suggested_max_seq_len"]
        assert sug & (sug - 1) == 0  # power of two
        assert sug >= result["p95_est_tokens"]
        assert sug < result["max_est_tokens"]  # P95 ignores the 5 outliers


class TestPreflight:
    def test_clean_split_is_ok(self):
        train = [_rec("A", body="aaa"), _rec("B", body="bbb")]
        valid = [_rec("C", body="ccc")]
        report = preflight(train, valid, QLoRAConfig())
        assert report["ok"] is True
        assert set(report["checks"]) == {"chat_shape", "split_disjoint", "length_budget"}

    def test_overall_not_ok_when_any_check_fails(self):
        train = [_rec("A", body="dup body")]
        valid = [_rec("A", body="dup body")]  # leakage
        report = preflight(train, valid, QLoRAConfig())
        assert report["ok"] is False
        assert report["checks"]["split_disjoint"]["ok"] is False

    def test_config_is_recorded(self):
        report = preflight([_rec("A")], [_rec("B")], QLoRAConfig.for_base("qwen2.5-3b"))
        assert report["config"]["base_model"] == QLoRAConfig.for_base("qwen2.5-3b").base_model


class TestRenderReport:
    def test_includes_headline_status_and_numbers(self):
        report = preflight([_rec("A", body="aaa")], [_rec("B", body="bbb")], QLoRAConfig())
        text = render_report(report)
        assert "PASS" in text or "FAIL" in text
        assert "chat" in text.lower()
        assert "max_seq_len" in text or "1024" in text

    def test_flags_failures_visibly(self):
        report = preflight([_rec("A", body="d")], [_rec("A", body="d")], QLoRAConfig())
        text = render_report(report)
        assert "FAIL" in text


class TestLoadSplit:
    def _seed(self, training_dir, train, heldout):
        training_dir.mkdir(parents=True, exist_ok=True)
        (training_dir / "train.jsonl").write_text("\n".join(json.dumps(r) for r in train) + "\n")
        (training_dir / "heldout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in heldout) + "\n"
        )

    def test_loads_train_and_heldout(self, tmp_path):
        training_dir = tmp_path / "training"
        self._seed(training_dir, [_rec("A")], [_rec("B")])
        train, valid = load_split(training_dir)
        assert len(train) == 1 and len(valid) == 1

    def test_raises_when_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="make training"):
            load_split(tmp_path / "nope")


class TestRunCli:
    def _seed(self, training_dir, train, heldout):
        training_dir.mkdir(parents=True, exist_ok=True)
        (training_dir / "train.jsonl").write_text("\n".join(json.dumps(r) for r in train) + "\n")
        (training_dir / "heldout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in heldout) + "\n"
        )

    def test_report_only_returns_zero_even_with_issues(self, tmp_path, capsys):
        training_dir = tmp_path / "training"
        self._seed(training_dir, [_rec("A", body="d")], [_rec("A", body="d")])
        code = run(["--training-dir", str(training_dir)])
        assert code == 0
        assert "FAIL" in capsys.readouterr().out

    def test_strict_returns_nonzero_on_issues(self, tmp_path):
        training_dir = tmp_path / "training"
        self._seed(training_dir, [_rec("A", body="d")], [_rec("A", body="d")])
        code = run(["--training-dir", str(training_dir), "--strict"])
        assert code == 1

    def test_strict_returns_zero_on_clean_split(self, tmp_path):
        training_dir = tmp_path / "training"
        self._seed(
            training_dir, [_rec("A", body="aaa"), _rec("B", body="bbb")], [_rec("C", body="ccc")]
        )
        code = run(["--training-dir", str(training_dir), "--strict"])
        assert code == 0

    def test_json_output_is_valid(self, tmp_path, capsys):
        training_dir = tmp_path / "training"
        self._seed(training_dir, [_rec("A", body="aaa")], [_rec("B", body="bbb")])
        run(["--training-dir", str(training_dir), "--json"])
        parsed = json.loads(capsys.readouterr().out)
        assert "checks" in parsed and "ok" in parsed
