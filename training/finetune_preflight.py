"""Pre-flight checks for the QLoRA fine-tune (plan 0008, de-risks step 26c).

Before anyone burns M4 compute on the actual training run, this validates 26a's
leakage-free split (`data/training/{train,heldout}.jsonl`) against the run's
`QLoRAConfig` and reports anything that would silently waste the run:

  - **chat-shape integrity** — every record is a system/user/assistant turn with
    non-empty content (mlx-lm needs well-formed chat records);
  - **split disjointness** — no training example leaks into the held-out/valid
    set (matched by assistant-content hash), which would inflate validation;
  - **sequence-length budget** — how many records' rendered prompts exceed the
    config's ``max_seq_len`` and would be dropped/truncated by mlx-lm.

It is **report-only** (exit 0) by default so it never turns `make verify` red;
``--strict`` exits non-zero on any failing check for a future CI/pre-run gate.
"""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

from training.finetune_config import (
    TRAINING_DIR,
    QLoRAConfig,
    load_jsonl,
    user_prompt,
)

# Rough offline token estimate. The real mlx-lm tokenizer is model-specific and
# needs the base downloaded; ~4 chars/token is the standard back-of-envelope for
# English and is plenty to flag records that blow past ``max_seq_len``.
DEFAULT_CHARS_PER_TOKEN = 4
MAX_EXAMPLES = 5


def assistant_content(record: dict) -> str | None:
    """The assistant-turn content of a chat record, or None if absent."""
    for m in record.get("messages", []):
        if m.get("role") == "assistant":
            return m.get("content")
    return None


def chat_shape_errors(record: dict) -> list[str]:
    """Problems with one record's chat shape; empty list means well-formed.

    mlx-lm expects each record to be a ``{"messages": [...]}`` chat with a
    non-empty system, user, and assistant turn. A missing or blank turn would
    train the model on a malformed example.
    """
    errors: list[str] = []
    messages = record.get("messages")
    if not messages:
        return ["no messages"]
    by_role = {m.get("role"): (m.get("content") or "") for m in messages}
    for role in ("system", "user", "assistant"):
        if role not in by_role:
            errors.append(f"missing {role} turn")
        elif not by_role[role].strip():
            errors.append(f"empty {role} content")
    return errors


def check_chat_shape(records: list[dict]) -> dict:
    """Aggregate chat-shape integrity over a list of records."""
    issues = []
    for i, rec in enumerate(records):
        errs = chat_shape_errors(rec)
        if errs:
            issues.append({"index": i, "errors": errs})
    return {
        "ok": not issues,
        "n": len(records),
        "n_malformed": len(issues),
        "issues": issues[:MAX_EXAMPLES],
    }


def _content_hash(text: str | None) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def check_split_disjoint(train: list[dict], valid: list[dict]) -> dict:
    """Detect held-out records that also appear in the training set.

    Overlap is keyed on the **assistant** content (the article body the model
    learns), so a body that leaks into both splits is caught even if its prompt
    was reworded. Any overlap inflates validation and breaks 26a's leakage-free
    guarantee.
    """
    train_hashes = {_content_hash(assistant_content(r)) for r in train}
    overlap: dict[str, str] = {}
    for r in valid:
        h = _content_hash(assistant_content(r))
        if h in train_hashes and h not in overlap:
            overlap[h] = user_prompt(r) or "(no prompt)"
    examples = [overlap[h] for h in sorted(overlap)][:MAX_EXAMPLES]
    return {"ok": not overlap, "n_overlap": len(overlap), "examples": examples}


def _record_chars(record: dict) -> int:
    return sum(len(m.get("content") or "") for m in record.get("messages", []))


def check_length_budget(
    records: list[dict], max_seq_len: int, chars_per_token: int = DEFAULT_CHARS_PER_TOKEN
) -> dict:
    """Estimate how many records exceed the run's ``max_seq_len``.

    Tokens are estimated from total chat character length (``chars/token``). A
    record over budget is dropped or truncated by mlx-lm — for full-article
    training records this is the most common way a run silently trains on
    almost nothing.
    """
    est = [_record_chars(r) / chars_per_token for r in records]
    n_over = sum(1 for t in est if t > max_seq_len)
    n = len(records)
    return {
        "ok": n_over == 0,
        "n": n,
        "n_over": n_over,
        "pct_over": round(100 * n_over / n, 1) if n else 0.0,
        "max_est_tokens": int(max(est)) if est else 0,
        "median_est_tokens": int(statistics.median(est)) if est else 0,
        "max_seq_len": max_seq_len,
        "chars_per_token": chars_per_token,
    }


def preflight(train: list[dict], valid: list[dict], config: QLoRAConfig) -> dict:
    """Run every pre-flight check and aggregate into one report dict."""
    checks = {
        "chat_shape": check_chat_shape(train + valid),
        "split_disjoint": check_split_disjoint(train, valid),
        "length_budget": check_length_budget(train + valid, config.max_seq_len),
    }
    return {
        "config": config.to_dict(),
        "n_train": len(train),
        "n_valid": len(valid),
        "checks": checks,
        "ok": all(c["ok"] for c in checks.values()),
    }


def render_report(report: dict) -> str:
    """Human-readable summary of a preflight report."""
    checks = report["checks"]
    lines = [
        f"QLoRA fine-tune preflight — {'PASS' if report['ok'] else 'FAIL'}",
        f"  base_model: {report['config']['base_model']}  max_seq_len: {report['config']['max_seq_len']}",
        f"  split: train={report['n_train']}  heldout/valid={report['n_valid']}",
        "",
    ]

    shape = checks["chat_shape"]
    lines.append(
        f"  [{'PASS' if shape['ok'] else 'FAIL'}] chat shape: "
        f"{shape['n'] - shape['n_malformed']}/{shape['n']} well-formed"
    )
    for issue in shape["issues"]:
        lines.append(f"        record #{issue['index']}: {', '.join(issue['errors'])}")

    disj = checks["split_disjoint"]
    lines.append(
        f"  [{'PASS' if disj['ok'] else 'FAIL'}] split disjoint: "
        f"{disj['n_overlap']} leaked record(s)"
    )
    for ex in disj["examples"]:
        lines.append(f"        leaked: {ex}")

    length = checks["length_budget"]
    lines.append(
        f"  [{'PASS' if length['ok'] else 'FAIL'}] length budget: "
        f"{length['n_over']}/{length['n']} ({length['pct_over']}%) over "
        f"max_seq_len={length['max_seq_len']} "
        f"(est tokens median={length['median_est_tokens']} max={length['max_est_tokens']}, "
        f"~{length['chars_per_token']} chars/token)"
    )
    if not length["ok"]:
        lines.append(
            "        → raise max_seq_len or chunk article bodies, else these records "
            "are dropped/truncated by mlx-lm."
        )

    return "\n".join(lines)


def load_split(training_dir=TRAINING_DIR) -> tuple[list[dict], list[dict]]:
    """Load 26a's ``train.jsonl`` / ``heldout.jsonl`` from ``training_dir``."""
    training_dir = Path(training_dir)
    train_src = training_dir / "train.jsonl"
    heldout_src = training_dir / "heldout.jsonl"
    missing = [str(p) for p in (train_src, heldout_src) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing 26a split file(s): " + ", ".join(missing) + ". Run `make training` first."
        )
    return load_jsonl(train_src), load_jsonl(heldout_src)


def run(argv=None) -> int:
    """CLI: preflight 26a's split against the QLoRA config. Returns an exit code."""
    parser = argparse.ArgumentParser(description="QLoRA fine-tune data preflight (plan 0008, 26c).")
    parser.add_argument("--training-dir", default=str(TRAINING_DIR), help="dir holding 26a's split")
    parser.add_argument(
        "--base", default=None, help="base-model alias or HF id (defaults to config)"
    )
    parser.add_argument("--max-seq-len", type=int, default=None, help="override config max_seq_len")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any check fails")
    args = parser.parse_args(argv)

    try:
        train, valid = load_split(args.training_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1 if args.strict else 0

    overrides = {}
    if args.max_seq_len is not None:
        overrides["max_seq_len"] = args.max_seq_len
    config = QLoRAConfig.for_base(args.base, **overrides) if args.base else QLoRAConfig(**overrides)

    report = preflight(train, valid, config)
    print(json.dumps(report, indent=2) if args.json else render_report(report))
    return 1 if (args.strict and not report["ok"]) else 0


if __name__ == "__main__":
    sys.exit(run())
