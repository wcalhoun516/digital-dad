"""Tests for analysis/voice_trials.py — the 26d voice-trials builder (plan 0008).

Pure shaping/IO logic only: turn 26a's held-out instruct records into a real
voice_trials.json skeleton (held-out prompt + a length-balanced `real` excerpt, with
`rag`/`finetuned` left as paste-here placeholders). Synthetic fixtures only — no real
corpus text — so committed tests carry no licensed article bodies.
"""

import json

from analysis.voice_trials import (
    FINETUNED_PLACEHOLDER,
    RAG_PLACEHOLDER,
    build_trial,
    build_trials,
    derive_prompt,
    excerpt,
    load_heldout,
    render_doc,
    write_trials,
)


def _record(user="Write an analysis of widgets.", body="The widget market is overbuilt."):
    return {
        "messages": [
            {"role": "system", "content": "You are Dr. George Calhoun."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": body},
        ]
    }


class TestDerivePrompt:
    def test_returns_user_turn(self):
        assert derive_prompt(_record(user="Write an analysis of the Fed.")) == (
            "Write an analysis of the Fed."
        )

    def test_returns_empty_when_no_user_turn(self):
        rec = {"messages": [{"role": "assistant", "content": "x"}]}
        assert derive_prompt(rec) == ""


class TestExcerpt:
    def test_short_text_unchanged(self):
        text = "A short passage."
        assert excerpt(text, max_chars=100) == "A short passage."

    def test_long_text_truncated_with_ellipsis(self):
        text = "word " * 100  # 500 chars
        out = excerpt(text, max_chars=40)
        assert out.endswith("…")
        assert len(out) <= 41  # 40 + ellipsis

    def test_truncation_does_not_split_a_word(self):
        text = "alpha beta gamma delta epsilon"
        out = excerpt(text, max_chars=14)  # mid-"gamma"
        assert out == "alpha beta…"  # cut at the last whole word


class TestBuildTrial:
    def test_id_is_zero_padded(self):
        assert build_trial(_record(), 1)["id"] == "v01"
        assert build_trial(_record(), 12)["id"] == "v12"

    def test_prompt_and_real_excerpt(self):
        rec = _record(user="Write about chips.", body="word " * 100)
        trial = build_trial(rec, 1, excerpt_chars=40)
        assert trial["prompt"] == "Write about chips."
        assert trial["candidates"]["real"].endswith("…")

    def test_rag_and_finetuned_are_placeholders(self):
        cand = build_trial(_record(), 1)["candidates"]
        assert cand["rag"] == RAG_PLACEHOLDER
        assert cand["finetuned"] == FINETUNED_PLACEHOLDER


class TestBuildTrials:
    def test_limit_caps_and_ids_are_sequential(self):
        recs = [_record(user=f"Prompt {i}") for i in range(5)]
        trials = build_trials(recs, limit=3)
        assert [t["id"] for t in trials] == ["v01", "v02", "v03"]

    def test_skips_records_missing_a_turn(self):
        recs = [_record(), {"messages": [{"role": "user", "content": "no body"}]}, _record()]
        trials = build_trials(recs)
        assert len(trials) == 2  # the bodiless record is dropped

    def test_seed_shuffle_is_reproducible(self):
        recs = [_record(user=f"Prompt {i}", body=f"body {i}") for i in range(8)]
        a = build_trials(recs, seed=42)
        b = build_trials(recs, seed=42)
        c = build_trials(recs, seed=7)
        assert [t["prompt"] for t in a] == [t["prompt"] for t in b]
        assert [t["prompt"] for t in a] != [t["prompt"] for t in c]


class TestRenderDoc:
    def test_doc_has_description_and_trials(self):
        doc = render_doc(build_trials([_record(), _record()]))
        assert "26d" in doc["description"]
        assert len(doc["trials"]) == 2


class TestWriteLoadRoundtrip:
    def test_write_then_load(self, tmp_path):
        path = tmp_path / "voice_trials.jsonl"
        recs = [_record(user="A"), _record(user="B")]
        write_trials({"trials": recs}, path)
        assert load_heldout(path.parent / "h.jsonl") == []  # missing file -> []
        loaded = json.loads(path.read_text())
        assert len(loaded["trials"]) == 2
