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

import csv
import json
from pathlib import Path

from analysis.utils import dedupe_manifest_entries, strip_wire_boilerplate
from training.finetune_config import QLoRAConfig
from training.finetune_preflight import DEFAULT_CHARS_PER_TOKEN
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
