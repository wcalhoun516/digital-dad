"""Build-time status snapshot for the Geo-LLM dashboard tab (plan 0008 insight).

Pure file readers (offline, no conductor): assemble ``data/analysis/geo_llm.json``
from the training artifacts + eval reports. Every field degrades to a safe default
when its source file is absent, so the dashboard build never breaks mid-experiment.
"""
import csv
import json
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


# Plan 0008 step ladder; the third tuple element is the artifact flag that marks it done.
_PIPELINE = [
    ("26a", "Dataset builder", "dataset"),
    ("26b", "Baseline captured", "rag"),
    ("26c", "QLoRA fine-tune notebook", "notebook"),
    ("26d", "Voice-fidelity eval harness", "voice_harness"),
    ("26e", "Train adapter & register", "adapter"),
    ("26f", "Compare & decide", "voice_results"),
]


def sample_pair(instruct_path: Path) -> dict | None:
    """First training example as a {prompt, answer} pair, or None if unavailable."""
    if not instruct_path.exists():
        return None
    with instruct_path.open() as fh:
        first = fh.readline()
    if not first.strip():
        return None
    msgs = json.loads(first).get("messages", [])
    prompt = next((m["content"] for m in msgs if m.get("role") == "user"), None)
    answer = next((m["content"] for m in msgs if m.get("role") == "assistant"), None)
    if not prompt or not answer:
        return None
    return {"prompt": prompt, "answer": answer}


def _summary(path: Path, keymap: dict) -> dict | None:
    """Read a report's ``summary`` block, renaming keys per *keymap* (None if absent)."""
    if not path.exists():
        return None
    summary = json.loads(path.read_text()).get("summary", {})
    return {out: summary.get(src) for out, src in keymap.items()}


def rag_summary(path: Path = ANALYSIS_DIR / "rag_eval.json") -> dict | None:
    """RAG faithfulness baseline — the bar the fine-tune must beat."""
    return _summary(path, {
        "grounding": "grounding_rate",
        "citation_coverage": "citation_coverage",
        "abstention_accuracy": "abstention_accuracy",
    })


def voice_summary(path: Path = ANALYSIS_DIR / "voice_eval.json") -> dict | None:
    """Pass the 26d voice-eval ``summary`` block through as-is (None until it exists).

    The template renders whatever keys are present, so there's no coupling to the
    exact metric names the owner-produced eval settles on.
    """
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("summary") or None


def pipeline_status(flags: dict) -> list[dict]:
    """Map 26a-f to status: done where the artifact flag is set, the first
    not-done step to ``next``, and everything after to ``upcoming``."""
    steps = []
    next_assigned = False
    for sid, label, flag in _PIPELINE:
        if flags.get(flag):
            status = "done"
        elif not next_assigned:
            status, next_assigned = "next", True
        else:
            status = "upcoming"
        steps.append({"id": sid, "label": label, "status": status})
    return steps
