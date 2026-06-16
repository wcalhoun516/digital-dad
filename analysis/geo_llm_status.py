"""Build-time status snapshot for the Geo-LLM dashboard tab (plan 0008 insight).

Pure file readers (offline, no conductor): assemble ``data/analysis/geo_llm.json``
from the training artifacts + eval reports. Every field degrades to a safe default
when its source file is absent, so the dashboard build never breaks mid-experiment.
"""
import csv
from pathlib import Path

from .utils import DATA_DIR

TRAINING_DIR = DATA_DIR / "training"
ANALYSIS_DIR = DATA_DIR / "analysis"
FINETUNE_RUN_DIR = DATA_DIR / "finetune_run"
REPORT_PATH = ANALYSIS_DIR / "geo_llm.json"


def _count_lines(path: Path) -> int:
    """Number of non-empty lines in *path* (0 if absent)."""
    if not path.exists():
        return 0
    with path.open() as fh:
        return sum(1 for line in fh if line.strip())


def count_geo_tokens(corpus_path: Path) -> int:
    """Whitespace token count of the training corpus (0 if absent)."""
    if not corpus_path.exists():
        return 0
    return len(corpus_path.read_text().split())


def dataset_stats(training_dir: Path = TRAINING_DIR) -> dict:
    """Counts + sizes for the training dataset; every field degrades to 0."""
    corpus = training_dir / "corpus.txt"
    meta = training_dir / "metadata.csv"
    n_columns = 0
    if meta.exists():
        with meta.open(newline="") as fh:
            n_columns = max(0, sum(1 for _ in csv.reader(fh)) - 1)  # minus header
    return {
        "n_examples": _count_lines(training_dir / "instruct.jsonl"),
        "n_train": _count_lines(training_dir / "train.jsonl"),
        "n_heldout": _count_lines(training_dir / "heldout.jsonl"),
        "n_columns": n_columns,
        "corpus_bytes": corpus.stat().st_size if corpus.exists() else 0,
        "geo_tokens": count_geo_tokens(corpus),
    }
