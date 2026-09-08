"""Prepare training data from the scraped corpus.

Outputs:
  - data/training/finetune.jsonl   — raw text, one JSON per line (all articles)
  - data/training/instruct.jsonl   — chat message format for instruction fine-tuning
  - data/training/train.jsonl      — passage records for the Geo LLM fine-tune (plan 0009)
  - data/training/heldout.jsonl    — held-out passage records for the voice eval
  - data/training/corpus.txt       — concatenated plain text, chronological
  - data/training/metadata.csv     — article metadata as CSV

Passage-level records (plan 0009, step 1):
  train.jsonl / heldout.jsonl hold **passages**, not whole articles. One record per article
  (completion = the entire body) was 3–5x the fine-tune's max_seq_len, so mlx-lm truncated
  every example and only ~33% of the corpus — always the article opening — ever reached the
  model. Bodies are chunked on paragraph boundaries into records that fit the window, with the
  task shape varied per passage. The split stays article-level (see below).

Train/held-out split (plan 0008, 26a):
  Quality articles are partitioned deterministically (by a stable slug hash) into train and
  held-out. Articles that a #25 RAG-eval question (eval/questions.json) is grounded in are
  reserved out of BOTH splits, so the voice fine-tune can't memorize the faithfulness eval's
  answers. When eval/questions.json is absent the exclusion is skipped (with a warning).

Quality filtering:
  Articles with word_count < 400 are excluded from instruct.jsonl (kept in finetune.jsonl).
  If linguistics.json exists, articles with type_token_ratio < 0.3 are also excluded from instruct.
"""

import csv
import hashlib
import json
import re
from pathlib import Path

from analysis.utils import chunk_text, dedupe_manifest_entries
from training.finetune_config import QLoRAConfig
from training.finetune_preflight import DEFAULT_CHARS_PER_TOKEN

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
TRAINING_DIR = DATA_DIR / "training"
MANIFEST_PATH = DATA_DIR / "manifest.json"
LINGUISTICS_PATH = DATA_DIR / "analysis" / "linguistics.json"
EVAL_QUESTIONS_PATH = ROOT_DIR / "eval" / "questions.json"

# Fraction of (non-eval-grounded) quality articles reserved for the held-out split.
HELDOUT_FRACTION = 0.15

SYSTEM_PROMPT = (
    "You are Dr. George Calhoun, a Forbes technology analyst and academic. "
    "You write incisive, data-driven analysis on telecommunications, semiconductors, "
    "technology policy, ESG, nuclear energy, and the intersection of economics and innovation. "
    "Your style is rigorous but accessible, often contrarian, and grounded in evidence. "
    "Write in first person, as Dr. Calhoun would."
)


def _article_to_topic(title: str) -> str:
    """Derive a writing prompt topic from an article title."""
    # Strip common leading question/article words
    topic = re.sub(r"^(why|how|what|when|where|is|are|the|a|an)\s+", "", title, flags=re.IGNORECASE)
    # Strip trailing question marks
    topic = topic.rstrip("?").strip()
    return topic or title


def build_instruct_record(title: str, body: str, system_prompt: str = SYSTEM_PROMPT) -> dict:
    """Shape one article into an instruction/chat record (prompt -> his-style passage)."""
    topic = _article_to_topic(title)
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Write an analysis of {topic}."},
            {"role": "assistant", "content": body},
        ]
    }


# The three moves the fine-tune should learn, not just "emit an article". One per
# record; the shape is stored on the record so the voice eval can slice by it.
TASK_SHAPES = ("write-on-topic", "continue-passage", "respond-to-claim")

_WRITE_TEMPLATE = "Write an analysis of {topic}."
_CONTINUE_TEMPLATE = "Continue this passage from your analysis of {topic}:\n\n{lead}"
_RESPOND_TEMPLATE = "On the subject of {topic}, respond to this claim:\n\n“{claim}”"

# The character estimate can't see the chat template's special tokens, so leave a
# little of the window unspent rather than land exactly on max_seq_len.
SEQ_HEADROOM = 0.95

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"“'A-Z0-9])")


def passage_budget_chars(config: QLoRAConfig | None = None) -> int:
    """Character budget for one whole training record under the run's window.

    Mirrors ``finetune_preflight.check_length_budget``'s arithmetic (total chat
    characters ÷ chars-per-token vs ``max_seq_len``) so a dataset built here
    passes the preflight that gates the run.
    """
    cfg = config or QLoRAConfig()
    return int(cfg.max_seq_len * DEFAULT_CHARS_PER_TOKEN * SEQ_HEADROOM)


def chunk_body(body: str, max_chars: int) -> list[str]:
    """Split an article body into passage-sized chunks of at most ``max_chars``.

    Chunks are packed on paragraph boundaries: a paragraph that fits is never
    divided, and consecutive paragraphs are grouped until the budget is reached.
    A single paragraph longer than the budget falls back to ``chunk_text`` (the
    corpus chunker Ask Dad retrieval already uses), which cuts at a sentence
    boundary. Overlap is off — repeated text would over-weight those sentences
    in the fine-tune.
    """
    paragraphs: list[str] = []
    for para in _PARAGRAPH_SPLIT.split(body or ""):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            paragraphs.append(para)
        else:
            paragraphs.extend(
                c for c in chunk_text(para, max_tokens=max(max_chars // 4, 1), overlap=0) if c
            )

    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for para in paragraphs:
        separator = 2 if current else 0  # the "\n\n" that will rejoin them
        if current and length + separator + len(para) > max_chars:
            chunks.append("\n\n".join(current))
            current, length = [], 0
            separator = 0
        current.append(para)
        length += separator + len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_lead(passage: str) -> tuple[str, str]:
    """Split a passage into its opening sentence and the remainder."""
    parts = _SENTENCE_SPLIT.split(passage.strip(), maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return passage.strip(), ""
    return parts[0].strip(), parts[1].strip()


def _prompt_overhead(topic: str) -> int:
    """Longest user-turn scaffolding across the shapes, for budgeting."""
    return max(
        len(_WRITE_TEMPLATE.format(topic=topic)),
        len(_CONTINUE_TEMPLATE.format(topic=topic, lead="")),
        len(_RESPOND_TEMPLATE.format(topic=topic, claim="")),
    )


def build_passage_record(
    title: str, passage: str, shape: str, system_prompt: str = SYSTEM_PROMPT
) -> dict:
    """Shape one passage into a chat record for the given task shape.

    ``continue-passage`` and ``respond-to-claim`` move the passage's opening
    sentence into the user turn, so the model learns to develop an argument it
    has been handed rather than only to start one. A passage with nothing after
    its opening sentence has no remainder to complete, so it falls back to
    ``write-on-topic`` rather than emitting an empty assistant turn.
    """
    if shape not in TASK_SHAPES:
        raise ValueError(f"unknown task shape: {shape!r} (expected one of {TASK_SHAPES})")

    topic = _article_to_topic(title)
    passage = passage.strip()

    if shape == "write-on-topic":
        user, assistant = _WRITE_TEMPLATE.format(topic=topic), passage
    else:
        lead, rest = _split_lead(passage)
        if not rest:
            shape, user, assistant = "write-on-topic", _WRITE_TEMPLATE.format(topic=topic), passage
        elif shape == "continue-passage":
            user, assistant = _CONTINUE_TEMPLATE.format(topic=topic, lead=lead), rest
        else:
            user, assistant = _RESPOND_TEMPLATE.format(topic=topic, claim=lead), rest

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "shape": shape,
    }


def _shape_for(slug: str, index: int) -> str:
    """Deterministic task shape for an article's ``index``-th passage.

    Rotates through the shapes so one article contributes several moves, offset
    by a stable hash of the slug so every article doesn't open on the same one.
    """
    offset = int(hashlib.md5(slug.encode()).hexdigest(), 16) if slug else 0
    return TASK_SHAPES[(offset + index) % len(TASK_SHAPES)]


def build_passage_records(
    title: str,
    body: str,
    slug: str = "",
    max_chars: int | None = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """Shape one article into in-budget passage records covering its whole body."""
    max_chars = passage_budget_chars() if max_chars is None else max_chars
    topic = _article_to_topic(title)
    passage_budget = max_chars - len(system_prompt) - _prompt_overhead(topic)
    return [
        build_passage_record(title, passage, _shape_for(slug, i), system_prompt)
        for i, passage in enumerate(chunk_body(body, passage_budget))
    ]


def _normalize_title(s: str) -> str:
    """Lowercase, fold typographic punctuation, and collapse to single-spaced tokens."""
    folded = (
        s.replace("’", "'")  # curly apostrophe
        .replace("‘", "'")
        .replace("“", '"')  # curly quotes
        .replace("”", '"')
        .replace("–", "-")  # en dash
        .replace("—", "-")  # em dash
    )
    # keep alphanumerics only, everything else becomes a separator
    tokens = re.findall(r"[a-z0-9]+", folded.lower())
    return " ".join(tokens)


def eval_grounded_slugs(questions: list[dict], articles: list[dict]) -> set[str]:
    """Slugs of corpus articles a #25 eval question is grounded in.

    An article is "eval-grounded" when its (normalized) title appears as a
    substring of the normalized text of some question's ``topic_hint`` /
    ``question``. These articles are reserved out of both the train and
    held-out splits so the voice fine-tune can't memorize the faithfulness
    eval's answers. Matching is deterministic and punctuation-robust.
    """
    haystacks = []
    for q in questions:
        text = f"{q.get('topic_hint', '')} {q.get('question', '')}"
        haystacks.append(_normalize_title(text))

    grounded: set[str] = set()
    for art in articles:
        norm_title = _normalize_title(art.get("title", ""))
        if len(norm_title.split()) < 3:
            continue  # too short to match safely
        if any(norm_title in hay for hay in haystacks):
            grounded.add(art["slug"])
    return grounded


def split_articles(
    slugs: list[str],
    heldout_frac: float = HELDOUT_FRACTION,
    excluded: set[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Deterministically partition slugs into (train, heldout).

    ``excluded`` slugs land in neither split. Membership is decided by a stable
    hash of the slug, so the partition is reproducible across runs and machines
    (independent of input ordering). Returns sorted lists.
    """
    train, heldout = [], []
    for slug in slugs:
        if slug in excluded:
            continue
        bucket = int(hashlib.md5(slug.encode()).hexdigest(), 16) % 1000
        if bucket < heldout_frac * 1000:
            heldout.append(slug)
        else:
            train.append(slug)
    return sorted(train), sorted(heldout)


def _write_split(path: Path, slugs: list[str], records: dict[str, list[dict]]) -> int:
    """Write every passage record for ``slugs`` (in order) to a JSONL file.

    Keyed by slug, so an article's passages cannot straddle the split.
    """
    written = 0
    with open(path, "w") as f:
        for slug in slugs:
            for record in records[slug]:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
    return written


def _load_eval_questions() -> list[dict]:
    """Return the #25 eval questions if the fixture is present, else []."""
    if not EVAL_QUESTIONS_PATH.exists():
        return []
    try:
        return json.loads(EVAL_QUESTIONS_PATH.read_text()).get("questions", [])
    except (json.JSONDecodeError, KeyError):
        return []


def run():
    if not MANIFEST_PATH.exists():
        print(f"Error: No manifest found at {MANIFEST_PATH}. Run `make scrape` first.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text())
    articles = dedupe_manifest_entries(manifest.get("articles", []))

    if not articles:
        print("No articles in manifest.")
        return

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    # Load TTR data from linguistics analysis if available
    ttr_by_slug: dict[str, float] = {}
    if LINGUISTICS_PATH.exists():
        try:
            ling = json.loads(LINGUISTICS_PATH.read_text())
            for a in ling.get("per_article", []):
                if a.get("slug") and a.get("type_token_ratio") is not None:
                    ttr_by_slug[a["slug"]] = a["type_token_ratio"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Load raw article data
    loaded = []
    for entry in sorted(articles, key=lambda a: a.get("date", "")):
        raw_path = DATA_DIR / entry["file"]
        if raw_path.exists():
            article = json.loads(raw_path.read_text())
            loaded.append((entry, article))

    print(f"Preparing training data from {len(loaded)} articles...")

    # Quality check for instruct format
    def _is_quality(entry: dict, article: dict) -> bool:
        wc = entry.get("word_count") or article.get("word_count") or 0
        if wc < 400:
            return False
        slug = entry.get("slug", "")
        ttr = ttr_by_slug.get(slug)
        if ttr is not None and ttr < 0.3:
            return False
        return True

    # 1. JSONL for fine-tuning (all articles, raw text)
    jsonl_path = TRAINING_DIR / "finetune.jsonl"
    with open(jsonl_path, "w") as f:
        for entry, article in loaded:
            body = article.get("body", "").strip()
            if body:
                f.write(json.dumps({"text": body}, ensure_ascii=False) + "\n")
    print(f"  JSONL (raw): {jsonl_path}  ({len(loaded)} articles)")

    # 2. Instruction-following JSONL (quality-filtered, chat message format)
    instruct_path = TRAINING_DIR / "instruct.jsonl"
    instruct_count = 0
    excluded_count = 0
    # slug -> passage records, for quality articles (drives the train/heldout split below)
    quality_records: dict[str, list[dict]] = {}
    with open(instruct_path, "w") as f:
        for entry, article in loaded:
            body = article.get("body", "").strip()
            if not body:
                continue
            if not _is_quality(entry, article):
                excluded_count += 1
                continue
            title = article.get("title") or entry.get("title") or "Untitled"
            record = build_instruct_record(title, body)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            instruct_count += 1
            slug = entry.get("slug", "")
            quality_records[slug] = build_passage_records(title, body, slug=slug)
    print(f"  JSONL (instruct): {instruct_path}  ({instruct_count} articles, {excluded_count} excluded by quality filter)")

    # 2b. Train / held-out split (plan 0008 26a) over the de-duplicated quality articles.
    #     The held-out split is reserved for the Geo LLM voice eval and must not overlap the
    #     #25 RAG eval questions; eval-grounded articles are dropped from both splits to keep
    #     the comparison leakage-free.
    eval_questions = _load_eval_questions()
    excluded_slugs = eval_grounded_slugs(eval_questions, [e for e, _ in loaded])
    train_slugs, heldout_slugs = split_articles(
        list(quality_records.keys()), excluded=excluded_slugs
    )
    n_train = _write_split(TRAINING_DIR / "train.jsonl", train_slugs, quality_records)
    n_heldout = _write_split(TRAINING_DIR / "heldout.jsonl", heldout_slugs, quality_records)
    if not eval_questions:
        print("  WARNING: eval/questions.json absent — held-out split NOT excluding #25 eval articles.")
    print(
        f"  Split: train.jsonl ({n_train} passages from {len(train_slugs)} articles) + "
        f"heldout.jsonl ({n_heldout} passages from {len(heldout_slugs)} articles); "
        f"{len(excluded_slugs)} eval-grounded article(s) reserved out of both."
    )

    # 3. Combined plain text corpus
    corpus_path = TRAINING_DIR / "corpus.txt"
    with open(corpus_path, "w") as f:
        for entry, article in loaded:
            title = article.get("title", entry.get("title", "Untitled"))
            date = (article.get("date", "") or entry.get("date", ""))[:10]
            body = article.get("body", "").strip()
            if body:
                f.write(f"# {title}\n")
                f.write(f"Date: {date}\n\n")
                f.write(body)
                f.write("\n\n---\n\n")
    print(f"  Corpus: {corpus_path}")

    # 4. Metadata CSV
    csv_path = TRAINING_DIR / "metadata.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "title", "date", "word_count", "tags", "url", "quality"])
        for entry, article in loaded:
            writer.writerow([
                entry.get("slug", ""),
                entry.get("title", ""),
                (entry.get("date", "") or "")[:10],
                entry.get("word_count", 0),
                "|".join(entry.get("tags", [])),
                entry.get("url", ""),
                "ok" if _is_quality(entry, article) else "filtered",
            ])
    print(f"  CSV: {csv_path}")

    print(f"\nTraining data ready: {len(loaded)} total, {instruct_count} quality articles for instruct tuning")


if __name__ == "__main__":
    run()
