"""Tests for analysis/voice_candidates.py — the eval's candidate generator.

The module's whole job is to turn a trial skeleton (``real`` filled, model arms empty)
into a complete trial set, so the tests concentrate on the two things that silently
corrupt an eval: picking the wrong checkpoint, and shipping a trial set that still has
placeholders in it.
"""

import json

import pytest

from analysis import voice_candidates as vc

TRAIN_LOG = """\
Loading pretrained model
Iter 1: Val loss 3.026, Val took 39.148s
Iter 25: Train loss 2.803, Learning Rate 1.000e-04, It/sec 0.382
Iter 100: Val loss 2.696, Val took 38.676s
Iter 200: Val loss 2.774, Val took 36.408s
Iter 1600: Val loss 3.058, Val took 34.224s
"""


# --- checkpoint selection --------------------------------------------------------

def test_parse_val_losses_reads_iter_and_loss():
    assert vc.parse_val_losses(TRAIN_LOG) == [
        (1, 3.026), (100, 2.696), (200, 2.774), (1600, 3.058)
    ]


def test_parse_val_losses_ignores_train_loss_lines():
    assert all(it != 25 for it, _ in vc.parse_val_losses(TRAIN_LOG))


def test_parse_val_losses_survives_carriage_returns():
    """mlx-lm writes tqdm progress with \\r; the log is not line-clean."""
    assert vc.parse_val_losses(TRAIN_LOG.replace("\n", "\r\n")) == vc.parse_val_losses(TRAIN_LOG)


def test_best_checkpoint_picks_lowest_val_loss_not_the_last():
    """The final adapter is usually overfit — this is the bug the module exists to avoid."""
    assert vc.best_checkpoint(vc.parse_val_losses(TRAIN_LOG)) == (100, 2.696)


def test_best_checkpoint_rejects_an_empty_log():
    with pytest.raises(ValueError, match="no val-loss"):
        vc.best_checkpoint([])


def test_best_checkpoint_breaks_ties_toward_the_earlier_iteration():
    assert vc.best_checkpoint([(100, 2.5), (200, 2.5)]) == (100, 2.5)


def test_checkpoint_filename_is_mlx_zero_padded():
    assert vc.checkpoint_filename(100) == "0000100_adapters.safetensors"
    assert vc.checkpoint_filename(1600) == "0001600_adapters.safetensors"


# --- arm resolution --------------------------------------------------------------

def test_resolve_arms_returns_specs_in_requested_order():
    arms = vc.resolve_arms(["rag", "finetuned"])
    assert [a.name for a in arms] == ["rag", "finetuned"]


def test_resolve_arms_rejects_an_unknown_arm_by_name():
    with pytest.raises(ValueError, match="nope"):
        vc.resolve_arms(["rag", "nope"])


def test_resolve_arms_rejects_real_which_is_not_generated():
    """`real` comes from the corpus, never from a model."""
    with pytest.raises(ValueError, match="real"):
        vc.resolve_arms(["real"])


def test_registry_covers_the_controls_the_eval_needs():
    """Both missing controls from D17 must be reachable, or the verdict stays confounded."""
    assert {"finetuned", "rag", "base-3b", "prompted-12b"} <= set(vc.ARM_REGISTRY)


def test_mlx_and_conductor_arms_are_distinguishable():
    assert vc.ARM_REGISTRY["finetuned"].kind == "mlx"
    assert vc.ARM_REGISTRY["rag"].kind == "conductor"


def test_only_the_rag_arm_retrieves():
    """prompted-12b is the no-retrieval control; if it retrieved it would just be rag."""
    assert vc.ARM_REGISTRY["rag"].retrieve is True
    assert vc.ARM_REGISTRY["prompted-12b"].retrieve is False


def test_base_3b_carries_no_adapter():
    """The un-tuned base is the control that says what fine-tuning actually added."""
    assert vc.ARM_REGISTRY["base-3b"].adapter_dir is None
    assert vc.ARM_REGISTRY["finetuned"].adapter_dir is not None


# --- filling candidates ----------------------------------------------------------

def _skeleton():
    return [
        {"id": "v01", "prompt": "p1", "candidates": {"real": "R1", "finetuned": "PASTE HERE"}},
        {"id": "v02", "prompt": "p2", "candidates": {"real": "R2", "finetuned": "PASTE HERE"}},
    ]


def test_fill_candidates_writes_text_per_trial_in_order():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["A1", "A2"])
    assert [t["candidates"]["finetuned"] for t in trials] == ["A1", "A2"]


def test_fill_candidates_leaves_real_untouched():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["A1", "A2"])
    assert [t["candidates"]["real"] for t in trials] == ["R1", "R2"]


def test_fill_candidates_adds_an_arm_that_was_not_in_the_skeleton():
    trials = vc.fill_candidates(_skeleton(), "base-3b", ["B1", "B2"])
    assert trials[0]["candidates"]["base-3b"] == "B1"


def test_fill_candidates_rejects_a_length_mismatch():
    """Silently zipping short would misalign every answer with the wrong prompt."""
    with pytest.raises(ValueError, match="2 trials"):
        vc.fill_candidates(_skeleton(), "finetuned", ["only-one"])


def test_fill_candidates_strips_surrounding_whitespace():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["  A1\n\n", "A2"])
    assert trials[0]["candidates"]["finetuned"] == "A1"


# --- the placeholder guard -------------------------------------------------------

def test_missing_candidates_flags_a_surviving_placeholder():
    trials = _skeleton()
    assert ("v01", "finetuned") in vc.missing_candidates(trials)


def test_missing_candidates_flags_an_empty_string():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["", "A2"])
    assert ("v01", "finetuned") in vc.missing_candidates(trials)


def test_missing_candidates_flags_whitespace_only():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["   ", "A2"])
    assert ("v01", "finetuned") in vc.missing_candidates(trials)


def test_missing_candidates_empty_when_every_arm_is_populated():
    trials = vc.fill_candidates(_skeleton(), "finetuned", ["A1", "A2"])
    assert vc.missing_candidates(trials) == []


# --- generation loop (injected seam) ---------------------------------------------

def test_generate_all_populates_every_requested_arm():
    calls = []

    def fake_generate(arm, prompts):
        calls.append(arm.name)
        return [f"{arm.name}-{i}" for i, _ in enumerate(prompts)]

    trials = vc.generate_all(_skeleton(), ["finetuned", "base-3b"], generate=fake_generate)
    assert calls == ["finetuned", "base-3b"]
    assert trials[0]["candidates"]["base-3b"] == "base-3b-0"
    assert vc.missing_candidates(trials) == []


def test_generate_all_raises_if_an_arm_returns_placeholders():
    """A generator that silently fails must not produce a shippable trial set."""
    def broken(arm, prompts):
        return ["" for _ in prompts]

    with pytest.raises(ValueError, match="incomplete"):
        vc.generate_all(_skeleton(), ["finetuned"], generate=broken)


def test_write_trials_round_trips_through_voice_eval_shape(tmp_path):
    """voice_eval.load_trials reads {"trials": [...]}; keep that contract."""
    from analysis import voice_eval

    trials = vc.generate_all(
        _skeleton(), ["finetuned"],
        generate=lambda arm, ps: [f"x{i}" for i, _ in enumerate(ps)],
    )
    out = tmp_path / "t.json"
    vc.write_trials(trials, out)
    assert voice_eval.load_trials(out) == json.loads(out.read_text())["trials"]
