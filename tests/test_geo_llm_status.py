"""Offline unit tests for analysis.geo_llm_status (build-time Geo-LLM tab data)."""
import csv
import json

from analysis import geo_llm_status as g


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_count_geo_tokens_whitespace(tmp_path):
    f = tmp_path / "corpus.txt"
    f.write_text("the bond market tells a story")  # 6 words
    assert g.count_geo_tokens(f) == 6


def test_count_geo_tokens_missing_returns_zero(tmp_path):
    assert g.count_geo_tokens(tmp_path / "nope.txt") == 0


def test_dataset_stats(tmp_path):
    tdir = tmp_path / "training"
    tdir.mkdir()
    _write_jsonl(tdir / "instruct.jsonl", [{"messages": []}] * 194)
    _write_jsonl(tdir / "train.jsonl", [{"messages": []}] * 138)
    _write_jsonl(tdir / "heldout.jsonl", [{"messages": []}] * 34)
    (tdir / "corpus.txt").write_text("a b c")  # 3 tokens, 5 bytes
    with (tdir / "metadata.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "title", "date"])
        w.writerow(["s", "t", "2020-01-01"])
        w.writerow(["s2", "t2", "2021-01-01"])
    s = g.dataset_stats(tdir)
    assert s["n_examples"] == 194
    assert s["n_train"] == 138
    assert s["n_heldout"] == 34
    assert s["n_columns"] == 2
    assert s["geo_tokens"] == 3
    assert s["corpus_bytes"] == 5


def test_dataset_stats_all_missing(tmp_path):
    s = g.dataset_stats(tmp_path / "empty")
    assert s["n_examples"] == 0
    assert s["n_columns"] == 0
    assert s["corpus_bytes"] == 0
    assert s["geo_tokens"] == 0


def test_sample_pair_extracts_user_and_assistant(tmp_path):
    f = tmp_path / "instruct.jsonl"
    rec = {"messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "What of the bond market?"},
        {"role": "assistant", "content": "The truth comes in layers..."}]}
    f.write_text(json.dumps(rec) + "\n")
    sp = g.sample_pair(f)
    assert sp["prompt"] == "What of the bond market?"
    assert sp["answer"].startswith("The truth")


def test_sample_pair_missing(tmp_path):
    assert g.sample_pair(tmp_path / "nope.jsonl") is None


def test_sample_pair_incomplete_returns_none(tmp_path):
    f = tmp_path / "instruct.jsonl"
    f.write_text(json.dumps({"messages": [{"role": "user", "content": "q"}]}) + "\n")
    assert g.sample_pair(f) is None


def test_rag_summary_reads_summary_block(tmp_path):
    f = tmp_path / "rag_eval.json"
    f.write_text(json.dumps({"summary": {
        "grounding_rate": 0.85, "citation_coverage": 0.6, "abstention_accuracy": 1.0}}))
    assert g.rag_summary(f) == {
        "grounding": 0.85, "citation_coverage": 0.6, "abstention_accuracy": 1.0}


def test_rag_summary_missing(tmp_path):
    assert g.rag_summary(tmp_path / "nope.json") is None


def test_voice_summary_passes_through_block(tmp_path):
    f = tmp_path / "voice_eval.json"
    f.write_text(json.dumps({"summary": {"voice_win_rate": 0.7, "n_trials": 10}}))
    assert g.voice_summary(f) == {"voice_win_rate": 0.7, "n_trials": 10}


def test_voice_summary_missing(tmp_path):
    assert g.voice_summary(tmp_path / "nope.json") is None


def test_pipeline_status_marks_done_then_next_then_upcoming():
    flags = {"dataset": True, "rag": True, "notebook": False,
             "voice_harness": False, "adapter": False, "voice_results": False}
    steps = g.pipeline_status(flags)
    by_id = {s["id"]: s["status"] for s in steps}
    assert by_id["26a"] == "done"
    assert by_id["26b"] == "done"
    assert by_id["26c"] == "next"       # first not-done becomes "next"
    assert by_id["26d"] == "upcoming"
    assert by_id["26f"] == "upcoming"
    assert [s["id"] for s in steps] == ["26a", "26b", "26c", "26d", "26e", "26f"]
