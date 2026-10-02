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

from training.finetune_config import QLoRAConfig
from training.finetune_preflight import DEFAULT_CHARS_PER_TOKEN
from training.prepare import SEQ_HEADROOM, chunk_body


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
