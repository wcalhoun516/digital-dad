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
    run,
    style_metrics,
    user_prompt,
    write_jsonl,
)
from training.finetune_preflight import PreflightError


def _rec(topic: str, body: str | None = None) -> dict:
    # The default body is topic-derived so distinct topics get distinct assistant
    # content. A shared body would read as a train/heldout leak to the staging gate.
    return {
        "messages": [
            {"role": "system", "content": "You are Dr. George Calhoun."},
            {"role": "user", "content": f"Write an analysis of {topic}."},
            {"role": "assistant", "content": body or f"An analysis of {topic}, at length."},
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
        assert counts == {"n_train": 3, "n_valid": 1, "preflight_ok": True}

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

    def test_stages_plain_chat_records_without_dataset_metadata(self, tmp_path):
        # Passage records (plan 0009) carry a "shape" for eval slicing; mlx-lm is
        # handed the chat turns only, so the trainer never sees our bookkeeping.
        training_dir = tmp_path / "training"
        finetune_dir = tmp_path / "run"
        train = [{**_rec("A"), "shape": "continue-passage"}]
        heldout = [{**_rec("B"), "shape": "respond-to-claim"}]
        self._seed_split(training_dir, train, heldout)

        prepare_mlx_data(training_dir, finetune_dir)

        staged = load_jsonl(finetune_dir / "train.jsonl") + load_jsonl(finetune_dir / "valid.jsonl")
        assert [set(r) for r in staged] == [{"messages"}, {"messages"}]
        assert staged[0]["messages"] == train[0]["messages"]

    def test_raises_when_26a_split_missing(self, tmp_path):
        training_dir = tmp_path / "training"
        training_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="make training"):
            prepare_mlx_data(training_dir, tmp_path / "run")


class TestStagingGate:
    """`prepare_mlx_data` is the only chokepoint that produces the files mlx-lm
    actually trains on — both `make finetune-prep` and the notebook go through it.
    Plan 0009 step 2: a dataset that fails the preflight must not get staged.
    """

    def _seed_split(self, training_dir, train, heldout):
        training_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(training_dir / "train.jsonl", train)
        write_jsonl(training_dir / "heldout.jsonl", heldout)

    def _dirs(self, tmp_path):
        return tmp_path / "training", tmp_path / "run"

    def test_refuses_to_stage_a_truncating_split(self, tmp_path):
        # The D15 defect: every record over max_seq_len, so mlx-lm trains on openings.
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError, match=r"\[FAIL\] length budget"):
            prepare_mlx_data(training_dir, finetune_dir)

    def test_refusal_stages_nothing(self, tmp_path):
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError):
            prepare_mlx_data(training_dir, finetune_dir)

        assert not (finetune_dir / "train.jsonl").exists()
        assert not (finetune_dir / "valid.jsonl").exists()

    def test_refuses_to_stage_a_leaked_split(self, tmp_path):
        # A body on both sides inflates validation — as run-wasting as truncation.
        training_dir, finetune_dir = self._dirs(tmp_path)
        shared = "The Fed's balance sheet is the story."
        self._seed_split(training_dir, [_rec("A", shared)], [_rec("B", shared)])

        with pytest.raises(PreflightError, match=r"\[FAIL\] split disjoint"):
            prepare_mlx_data(training_dir, finetune_dir)

    def test_refuses_to_stage_a_malformed_chat_record(self, tmp_path):
        training_dir, finetune_dir = self._dirs(tmp_path)
        headless = {"messages": [{"role": "user", "content": "Write something."}]}
        self._seed_split(training_dir, [headless], [_rec("B")])

        with pytest.raises(PreflightError, match=r"\[FAIL\] chat shape"):
            prepare_mlx_data(training_dir, finetune_dir)

    def test_refusal_carries_the_actionable_report(self, tmp_path):
        # A bare "preflight failed" would send the owner back to the CLI to find out
        # why. The rendered report — counts, medians, the suggested fix — comes along.
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError) as exc:
            prepare_mlx_data(training_dir, finetune_dir)

        message = str(exc.value)
        assert "2/2 (100.0%) over max_seq_len=1024" in message
        assert "chunk article bodies" in message

    def test_gate_respects_a_supplied_config(self, tmp_path):
        # Same data, two budgets: the gate reads the config the run will actually use,
        # not a hardcoded 1024.
        training_dir, finetune_dir = self._dirs(tmp_path)
        body = "A paragraph of real argument. " * 60  # ~1800 chars ≈ 450 tokens
        self._seed_split(training_dir, [_rec("A", body)], [_rec("B", body + "!")])

        counts = prepare_mlx_data(training_dir, finetune_dir, config=QLoRAConfig())
        assert counts["n_train"] == 1

        with pytest.raises(PreflightError, match=r"\[FAIL\] length budget"):
            prepare_mlx_data(training_dir, finetune_dir, config=QLoRAConfig(max_seq_len=128))

    def test_force_stages_a_failing_split_anyway(self, tmp_path):
        # Step 4 may want to reproduce D15's original truncating run for comparison.
        # The override exists, but it is a deliberate argument, never a default.
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        train = [_rec("A", long_body)]
        self._seed_split(training_dir, train, [_rec("B", long_body + "!")])

        counts = prepare_mlx_data(training_dir, finetune_dir, force=True)

        assert counts["n_train"] == 1
        assert load_jsonl(finetune_dir / "train.jsonl") == train

    def test_force_reports_that_the_gate_was_overridden(self, tmp_path):
        # Forcing must leave a trace in the return value, so the notebook's run summary
        # records that this run trained on data the preflight rejected.
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        counts = prepare_mlx_data(training_dir, finetune_dir, force=True)

        assert counts["preflight_ok"] is False

    def test_clean_split_reports_a_passing_preflight(self, tmp_path):
        training_dir, finetune_dir = self._dirs(tmp_path)
        self._seed_split(training_dir, [_rec("A"), _rec("B")], [_rec("C")])

        counts = prepare_mlx_data(training_dir, finetune_dir)

        assert counts["preflight_ok"] is True

    def test_refusal_names_stale_already_staged_files(self, tmp_path):
        # The real hazard: a previous run left train.jsonl in place, so `mlx_lm.lora
        # --data` would happily train on last run's data while this one refused.
        training_dir, finetune_dir = self._dirs(tmp_path)
        finetune_dir.mkdir(parents=True)
        write_jsonl(finetune_dir / "train.jsonl", [_rec("stale")])
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError, match="stale"):
            prepare_mlx_data(training_dir, finetune_dir)

    def test_refusal_leaves_stale_files_untouched(self, tmp_path):
        # Naming them is the job; deleting the owner's files is not.
        training_dir, finetune_dir = self._dirs(tmp_path)
        finetune_dir.mkdir(parents=True)
        stale = [_rec("stale")]
        write_jsonl(finetune_dir / "train.jsonl", stale)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError):
            prepare_mlx_data(training_dir, finetune_dir)

        assert load_jsonl(finetune_dir / "train.jsonl") == stale

    def test_no_stale_warning_when_nothing_was_staged_before(self, tmp_path):
        training_dir, finetune_dir = self._dirs(tmp_path)
        long_body = "This is a sustained argument. " * 900
        self._seed_split(training_dir, [_rec("A", long_body)], [_rec("B", long_body + "!")])

        with pytest.raises(PreflightError) as exc:
            prepare_mlx_data(training_dir, finetune_dir)

        assert "stale" not in str(exc.value)


class TestStagingCLI:
    def _seed(self, tmp_path, body):
        training_dir = tmp_path / "training"
        training_dir.mkdir(parents=True)
        write_jsonl(training_dir / "train.jsonl", [_rec("A", body)])
        write_jsonl(training_dir / "heldout.jsonl", [_rec("B", body + "!")])
        return training_dir

    def test_exits_nonzero_when_the_gate_refuses(self, tmp_path, capsys):
        training_dir = self._seed(tmp_path, "This is a sustained argument. " * 900)

        code = run(["--training-dir", str(training_dir), "--finetune-dir", str(tmp_path / "run")])

        assert code == 1
        assert "length budget" in capsys.readouterr().out

    def test_exits_zero_on_a_clean_split(self, tmp_path):
        training_dir = self._seed(tmp_path, "A short, well-formed body.")

        code = run(["--training-dir", str(training_dir), "--finetune-dir", str(tmp_path / "run")])

        assert code == 0

    def test_force_flag_exits_zero_and_stages(self, tmp_path, capsys):
        training_dir = self._seed(tmp_path, "This is a sustained argument. " * 900)
        finetune_dir = tmp_path / "run"

        code = run(
            ["--training-dir", str(training_dir), "--finetune-dir", str(finetune_dir), "--force"]
        )

        assert code == 0
        assert (finetune_dir / "train.jsonl").exists()
        assert "WARNING" in capsys.readouterr().out

    def test_missing_split_exits_nonzero(self, tmp_path, capsys):
        empty = tmp_path / "training"
        empty.mkdir()

        code = run(["--training-dir", str(empty), "--finetune-dir", str(tmp_path / "run")])

        assert code == 1
        assert "make training" in capsys.readouterr().out


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
