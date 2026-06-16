"""Tests for training/finetune_config.py — the reproducible QLoRA notebook layer
(plan 0008, step 26c).

Covers the deterministic pieces the notebook imports: config resolution, the
leakage-safe staging of 26a's split into mlx-lm's expected layout, deterministic
eval-prompt selection, and the pure style metrics. No MLX, no model download.
"""

import json

import pytest

from training.finetune_config import (
    DEFAULT_BASE,
    SMALL_BASES,
    QLoRAConfig,
    eval_prompts,
    load_jsonl,
    prepare_mlx_data,
    style_metrics,
    user_prompt,
    write_jsonl,
)


def _rec(topic: str, body: str = "Some analysis body that is reasonably long.") -> dict:
    return {
        "messages": [
            {"role": "system", "content": "You are Dr. George Calhoun."},
            {"role": "user", "content": f"Write an analysis of {topic}."},
            {"role": "assistant", "content": body},
        ]
    }


class TestQLoRAConfig:
    def test_defaults_match_small_local_base(self):
        cfg = QLoRAConfig()
        assert cfg.base_model == DEFAULT_BASE
        assert cfg.lora_rank > 0 and cfg.lora_layers > 0
        assert cfg.train_iters > 0

    def test_for_base_resolves_registry_key(self):
        cfg = QLoRAConfig.for_base("gemma-2-2b")
        assert cfg.base_model == SMALL_BASES["gemma-2-2b"]

    def test_for_base_accepts_raw_hf_id(self):
        cfg = QLoRAConfig.for_base("some-org/Custom-1B")
        assert cfg.base_model == "some-org/Custom-1B"

    def test_for_base_applies_overrides(self):
        cfg = QLoRAConfig.for_base("phi3-mini", train_iters=500, lora_rank=16)
        assert cfg.train_iters == 500
        assert cfg.lora_rank == 16

    def test_to_dict_is_json_serializable(self):
        # the notebook's run-summary dumps the config; it must survive json.dumps
        json.dumps(QLoRAConfig().to_dict())


class TestJsonl:
    def test_roundtrip(self, tmp_path):
        records = [_rec("Inflation"), _rec("The Fed")]
        path = tmp_path / "x.jsonl"
        write_jsonl(path, records)
        assert load_jsonl(path) == records

    def test_load_skips_blank_lines(self, tmp_path):
        path = tmp_path / "x.jsonl"
        path.write_text(json.dumps(_rec("A")) + "\n\n" + json.dumps(_rec("B")) + "\n")
        assert len(load_jsonl(path)) == 2


class TestPrepareMlxData:
    def _seed_split(self, training_dir, train, heldout):
        training_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(training_dir / "train.jsonl", train)
        write_jsonl(training_dir / "heldout.jsonl", heldout)

    def test_stages_26a_split_into_mlx_layout(self, tmp_path):
        training_dir = tmp_path / "training"
        finetune_dir = tmp_path / "run"
        train = [_rec("A"), _rec("B"), _rec("C")]
        heldout = [_rec("D")]
        self._seed_split(training_dir, train, heldout)

        counts = prepare_mlx_data(training_dir, finetune_dir)

        # mlx_lm.lora reads train.jsonl + valid.jsonl from its --data dir
        assert load_jsonl(finetune_dir / "train.jsonl") == train
        assert load_jsonl(finetune_dir / "valid.jsonl") == heldout
        assert counts == {"n_train": 3, "n_valid": 1}

    def test_valid_set_is_the_leakage_free_heldout_not_a_reshuffle(self, tmp_path):
        # The whole point of 26c: validation comes from 26a's heldout.jsonl verbatim,
        # never a random re-split of the (eval-contaminated) instruct.jsonl.
        training_dir = tmp_path / "training"
        finetune_dir = tmp_path / "run"
        train = [_rec(f"train-{i}") for i in range(10)]
        heldout = [_rec("heldout-only")]
        self._seed_split(training_dir, train, heldout)

        prepare_mlx_data(training_dir, finetune_dir)

        valid = load_jsonl(finetune_dir / "valid.jsonl")
        assert valid == heldout
        assert all(user_prompt(r) != "Write an analysis of heldout-only." for r in train)

    def test_raises_when_26a_split_missing(self, tmp_path):
        training_dir = tmp_path / "training"
        training_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="make training"):
            prepare_mlx_data(training_dir, tmp_path / "run")


class TestEvalPrompts:
    def test_returns_first_n_user_prompts_in_order(self):
        records = [_rec("A"), _rec("B"), _rec("C")]
        assert eval_prompts(records, n=2) == [
            "Write an analysis of A.",
            "Write an analysis of B.",
        ]

    def test_is_deterministic(self):
        records = [_rec(c) for c in "XYZW"]
        assert eval_prompts(records) == eval_prompts(records)

    def test_dedupes_repeated_prompts(self):
        records = [_rec("A"), _rec("A"), _rec("B")]
        assert eval_prompts(records, n=5) == [
            "Write an analysis of A.",
            "Write an analysis of B.",
        ]

    def test_user_prompt_returns_none_without_user_message(self):
        assert user_prompt({"messages": [{"role": "system", "content": "x"}]}) is None


class TestStyleMetrics:
    def test_counts_and_ratios(self):
        text = "The Fed prints alpha. Alpha is real money for the savvy investor."
        m = style_metrics(text, distinctive_words={"alpha", "fed"})
        assert m["word_count"] == 12
        assert 0 < m["type_token_ratio"] <= 1
        assert m["fingerprint_hits_per_1k"] > 0

    def test_empty_text_is_safe(self):
        m = style_metrics("", distinctive_words={"alpha"})
        assert m["word_count"] == 0
        assert m["type_token_ratio"] == 0
        assert m["fingerprint_hits_per_1k"] == 0

    def test_fingerprint_rate_scales_with_distinctive_hits(self):
        text = "alpha beta gamma delta"
        few = style_metrics(text, distinctive_words={"alpha"})
        many = style_metrics(text, distinctive_words={"alpha", "beta", "gamma"})
        assert many["fingerprint_hits_per_1k"] > few["fingerprint_hits_per_1k"]
