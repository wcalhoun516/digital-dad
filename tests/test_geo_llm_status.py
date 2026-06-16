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
