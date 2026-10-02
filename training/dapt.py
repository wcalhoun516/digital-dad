"""DAPT dataset: his raw prose for continued pretraining (roadmap #54).

ADR D19's diagnosis of why the instruction-pair LoRA lost to its own base: on ~453K tokens,
"Write an analysis of X" → article is cheapest to fit by reproducing surface markers (hinge
vocabulary up 3.5x, lexical variety down two-thirds). Domain-adaptive pretraining keeps the
same tokens and drops the format — plain ``{"text": ...}`` records, no system prompt, no user
turn, so there is no prompt→answer mapping to mimic, only the next word of his prose.

**Same tokens, different objective** is the whole point, so the comparison has to hold the
tokens fixed. The DAPT train set is exactly the instruction set's train articles and its
validation set exactly their held-out articles:

- article membership is read from ``make training``'s own ``metadata.csv`` (``quality: ok``
  rows), so this module inherits the quality filter — and any admission policy ``prepare``
  applies before writing it — instead of keeping a second copy that could drift;
- the split is recomputed with ``prepare.split_articles`` and ``prepare.eval_grounded_slugs``,
  the same functions that wrote ``train.jsonl`` / ``heldout.jsonl``;
- bodies get the same cleaning (wire boilerplate, then the cross-article footer paragraphs).

Run ``make training`` first, then ``make dapt-prep``.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from analysis.utils import dedupe_manifest_entries, strip_wire_boilerplate
from training.finetune_config import FINETUNE_DIR, QLoRAConfig, _refusal_message, write_jsonl
from training.finetune_preflight import (
    DEFAULT_CHARS_PER_TOKEN,
    MAX_EXAMPLES,
    PreflightError,
    assistant_content,
    check_length_budget,
    load_split,
)
from training.prepare import (
    DATA_DIR,
    EVAL_QUESTIONS_PATH,
    SEQ_HEADROOM,
    TRAINING_DIR,
    boilerplate_paragraphs,
    chunk_body,
    eval_grounded_slugs,
    split_articles,
    strip_boilerplate,
)

# Its own mlx-lm ``--data`` directory: the trainer reads every file in it, so the text records
# must never sit beside the instruction set's chat records.
DAPT_DIR = FINETUNE_DIR / "dapt"

# Shingle width for the held-out leak check — the same 8 words the exemplar guard uses.
SHINGLE_WORDS = 8


def dapt_budget_chars(config: QLoRAConfig | None = None) -> int:
    """Character budget for one text record under the run's ``max_seq_len``.

    The same arithmetic as ``prepare.passage_budget_chars``; the difference is that a DAPT
    record spends all of it on his prose, where a chat record pays for its prompts first.
    """
    cfg = config or QLoRAConfig()
    return int(cfg.max_seq_len * DEFAULT_CHARS_PER_TOKEN * SEQ_HEADROOM)


def build_dapt_records(body: str, max_chars: int | None = None) -> list[dict]:
    """One article body → in-budget ``{"text"}`` records, packed on paragraph boundaries."""
    max_chars = dapt_budget_chars() if max_chars is None else max_chars
    return [{"text": chunk} for chunk in chunk_body(body, max_chars)]


def _load_questions(path: Path) -> list[dict]:
    """The #25 eval questions, or [] — the same fallback ``prepare`` uses."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("questions", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def load_dapt_split(
    training_dir=TRAINING_DIR,
    data_dir=DATA_DIR,
    questions_path=EVAL_QUESTIONS_PATH,
    max_chars: int | None = None,
) -> dict:
    """Build the DAPT ``train`` / ``valid`` text records on the instruction set's own split.

    ``metadata.csv`` lists every article ``prepare`` loaded, with its quality verdict; that is
    the membership. Bodies are re-read from ``data/raw`` and cleaned the way ``prepare`` cleans
    passage records. Returns ``{"train", "valid", "n_train_articles", "n_valid_articles",
    "n_reserved"}``; raises ``FileNotFoundError`` if ``make training`` has not run.
    """
    training_dir, data_dir = Path(training_dir), Path(data_dir)
    metadata = training_dir / "metadata.csv"
    if not metadata.exists():
        raise FileNotFoundError(f"Missing {metadata}. Run `make training` first.")
    with open(metadata, newline="") as f:
        rows = list(csv.DictReader(f))

    manifest = json.loads((data_dir / "manifest.json").read_text())
    files = {
        e["slug"]: e.get("file") for e in dedupe_manifest_entries(manifest.get("articles", []))
    }
    raw_bodies: dict[str, str] = {}
    for row in rows:
        path = data_dir / (files.get(row["slug"]) or "")
        if path.is_file():
            raw_bodies[row["slug"]] = json.loads(path.read_text()).get("body", "")

    # Footer detection runs over every loaded article, quality or not — as in prepare.
    boilerplate = boilerplate_paragraphs(
        raw_bodies[r["slug"]] for r in rows if r["slug"] in raw_bodies
    )
    records: dict[str, list[dict]] = {}
    for row in rows:
        body = strip_wire_boilerplate(raw_bodies.get(row["slug"], ""))
        if row.get("quality") == "ok" and body:
            records[row["slug"]] = build_dapt_records(
                strip_boilerplate(body, boilerplate), max_chars
            )

    reserved = eval_grounded_slugs(_load_questions(Path(questions_path)), rows)
    train_slugs, valid_slugs = split_articles(list(records), excluded=reserved)
    return {
        "train": [r for slug in train_slugs for r in records[slug]],
        "valid": [r for slug in valid_slugs for r in records[slug]],
        "n_train_articles": len(train_slugs),
        "n_valid_articles": len(valid_slugs),
        "n_reserved": len(reserved & set(records)),
    }


# --- preflight ----------------------------------------------------------------------------


def _squash(text: str) -> str:
    """Whitespace-insensitive form for containment: the two chunkers break lines differently."""
    return re.sub(r"\s+", " ", text or "").strip()


def _shingles(text: str, n: int = SHINGLE_WORDS) -> set[str]:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _chat_prose(record: dict) -> str:
    """His prose in a chat record: the assistant turn plus any lead the user turn quotes."""
    return "\n".join(
        m.get("content") or "" for m in record.get("messages", []) if m.get("role") != "system"
    )


def check_text_shape(records: list[dict]) -> dict:
    """Every record is ``{"text": <non-empty>}`` and nothing else — no chat turns."""
    bad = [i for i, r in enumerate(records) if set(r) != {"text"} or not str(r["text"]).strip()]
    return {
        "ok": not bad,
        "n": len(records),
        "n_malformed": len(bad),
        "indexes": bad[:MAX_EXAMPLES],
    }


def check_text_disjoint(train: list[dict], valid: list[dict]) -> dict:
    """No identical record on both sides of the split."""
    digest = lambda r: hashlib.sha1(_squash(r.get("text")).encode()).hexdigest()  # noqa: E731
    overlap = {digest(r) for r in train} & {digest(r) for r in valid}
    return {"ok": not overlap, "n_overlap": len(overlap)}


def check_same_split(
    train: list[dict], valid: list[dict], instr_train: list[dict], instr_heldout: list[dict]
) -> dict:
    """Every instruction passage sits inside the DAPT prose on its own side — and not the other.

    This is what makes the arms comparable — same tokens, different objective. A passage
    missing from its side is what a stale ``make training`` looks like (passages from a corpus
    that has since changed); a passage found on the *other* side is a held-out article that
    DAPT would train on.
    """
    prose = {
        side: _squash(" ".join(r.get("text") or "" for r in records))
        for side, records in (("train", train), ("valid", valid))
    }
    result: dict = {"ok": True}
    for side, other, instr in (("train", "valid", instr_train), ("valid", "train", instr_heldout)):
        passages = [assistant_content(r) or "" for r in instr]
        missing = [p for p in passages if _squash(p) not in prose[side]]
        crossed = [p for p in passages if _squash(p) in prose[other]]
        result[f"n_missing_{side}"] = len(missing)
        result[f"n_crossed_{side}"] = len(crossed)
        result[f"examples_{side}"] = [
            f"{kind}: {p[:80]}"
            for kind, p in (
                [("missing", p) for p in missing] + [("on the wrong side", p) for p in crossed]
            )[:MAX_EXAMPLES]
        ]
        result["ok"] = result["ok"] and not missing and not crossed
    return result


def check_heldout_overlap(
    train: list[dict], instr_train: list[dict], instr_heldout: list[dict]
) -> dict:
    """DAPT train may see no held-out 8-gram the instruction train does not already see.

    An absolute zero is the wrong bar: he reused passages across columns, so the instruction
    split already shares hundreds of 8-grams with its own held-out set (318 on 2026-10-02).
    What must hold is that DAPT adds none — otherwise its validation loss is flattered relative
    to the arm it is being compared with.
    """
    heldout = set().union(*(_shingles(_chat_prose(r)) for r in instr_heldout))
    already = heldout & set().union(*(_shingles(_chat_prose(r)) for r in instr_train))
    seen = heldout & set().union(*(_shingles(r.get("text")) for r in train))
    new = sorted(seen - already)
    return {
        "ok": not new,
        "n_new": len(new),
        "n_shared_with_instruction": len(seen & already),
        "examples": new[:MAX_EXAMPLES],
    }


def dapt_preflight(
    train: list[dict],
    valid: list[dict],
    instr_train: list[dict],
    instr_heldout: list[dict],
    config: QLoRAConfig | None = None,
) -> dict:
    """Run every DAPT check and aggregate into one report dict."""
    config = config or QLoRAConfig()
    checks = {
        "text_shape": check_text_shape(train + valid),
        "split_disjoint": check_text_disjoint(train, valid),
        "length_budget": check_length_budget(train + valid, config.max_seq_len),
        "same_split": check_same_split(train, valid, instr_train, instr_heldout),
        "heldout_overlap": check_heldout_overlap(train, instr_train, instr_heldout),
    }
    return {
        "config": config.to_dict(),
        "n_train": len(train),
        "n_valid": len(valid),
        "checks": checks,
        "ok": all(c["ok"] for c in checks.values()),
    }


def render_dapt_report(report: dict) -> str:
    """Human-readable summary of a DAPT preflight report."""
    c = report["checks"]
    mark = lambda check: "PASS" if check["ok"] else "FAIL"  # noqa: E731
    shape, disj, length = c["text_shape"], c["split_disjoint"], c["length_budget"]
    same, overlap = c["same_split"], c["heldout_overlap"]
    lines = [
        f"DAPT preflight — {'PASS' if report['ok'] else 'FAIL'}",
        f"  max_seq_len: {report['config']['max_seq_len']}  "
        f"split: train={report['n_train']}  valid={report['n_valid']}",
        "",
        f"  [{mark(shape)}] text shape: {shape['n'] - shape['n_malformed']}/{shape['n']} plain text records",
        f"  [{mark(disj)}] split disjoint: {disj['n_overlap']} record(s) on both sides",
        f"  [{mark(length)}] length budget: {length['n_over']}/{length['n']} over max_seq_len "
        f"(est tokens median={length['median_est_tokens']} max={length['max_est_tokens']})",
        f"  [{mark(same)}] same split as the instruction set: "
        f"missing {same['n_missing_train']} train / {same['n_missing_valid']} heldout passage(s), "
        f"on the wrong side {same['n_crossed_train']} / {same['n_crossed_valid']}",
    ]
    for side in ("train", "valid"):
        lines += [f"        {side}, {ex}…" for ex in same[f"examples_{side}"]]
    if same["n_missing_train"] or same["n_missing_valid"]:
        lines.append("        → re-run `make training`; the split files predate the corpus.")
    lines.append(
        f"  [{mark(overlap)}] heldout 8-grams: {overlap['n_new']} new beyond the instruction "
        f"train ({overlap['n_shared_with_instruction']} shared by both arms — his own reuse)"
    )
    lines += [f"        new: {ex}" for ex in overlap["examples"]]
    return "\n".join(lines)


# --- staging ------------------------------------------------------------------------------


def stage_dapt_data(
    training_dir=TRAINING_DIR,
    data_dir=DATA_DIR,
    questions_path=EVAL_QUESTIONS_PATH,
    out_dir=DAPT_DIR,
    config: QLoRAConfig | None = None,
    force: bool = False,
) -> dict:
    """Write mlx-lm's ``train.jsonl`` / ``valid.jsonl`` for DAPT into ``out_dir``.

    The same contract as ``finetune_config.prepare_mlx_data``: a set that fails any check
    raises ``PreflightError`` and **nothing is written**; ``force=True`` overrides it.
    """
    config = config or QLoRAConfig()
    out_dir = Path(out_dir)
    split = load_dapt_split(training_dir, data_dir, questions_path, dapt_budget_chars(config))
    instr_train, instr_heldout = load_split(training_dir)
    report = dapt_preflight(split["train"], split["valid"], instr_train, instr_heldout, config)
    if not report["ok"] and not force:
        raise PreflightError(_refusal_message(render_dapt_report(report), out_dir))

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "train.jsonl", split["train"])
    write_jsonl(out_dir / "valid.jsonl", split["valid"])
    return {
        "n_train": len(split["train"]),
        "n_valid": len(split["valid"]),
        "n_train_articles": split["n_train_articles"],
        "n_valid_articles": split["n_valid_articles"],
        "preflight_ok": report["ok"],
        "report": report,
    }


def run(argv=None) -> int:
    """CLI: build, preflight and stage the DAPT data (offline, free). Returns an exit code."""
    parser = argparse.ArgumentParser(description="Stage the DAPT raw-prose dataset (roadmap #54).")
    parser.add_argument("--training-dir", default=str(TRAINING_DIR), help="`make training` output")
    parser.add_argument("--out-dir", default=str(DAPT_DIR), help="mlx-lm --data dir for DAPT")
    parser.add_argument("--max-seq-len", type=int, default=None, help="override max_seq_len")
    parser.add_argument("--force", action="store_true", help="stage even if the preflight fails")
    args = parser.parse_args(argv)

    overrides = {} if args.max_seq_len is None else {"max_seq_len": args.max_seq_len}
    try:
        counts = stage_dapt_data(
            args.training_dir,
            out_dir=args.out_dir,
            config=QLoRAConfig(**overrides),
            force=args.force,
        )
    except (FileNotFoundError, PreflightError) as e:
        print(e)
        return 1

    print(render_dapt_report(counts["report"]))
    if not counts["preflight_ok"]:
        print("\nWARNING: --force staged a set the preflight rejected; it is not comparable.")
    print(
        f"\nStaged DAPT data in {args.out_dir}: train={counts['n_train']} records "
        f"({counts['n_train_articles']} articles), valid={counts['n_valid']} "
        f"({counts['n_valid_articles']} articles)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
