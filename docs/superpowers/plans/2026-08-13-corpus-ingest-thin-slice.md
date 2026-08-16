# Corpus II — Provenance + Ingest Thin Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a file dropped in `data/inbox/` travel through extraction and human review into the corpus, carrying provenance that says what it is and how we got it.

**Architecture:** A new stdlib-only `ingest/` package. Format handlers are pure functions in a registry keyed by file extension, so adding a format later is an isolated PR. Extraction never touches the corpus — it stages JSON into a queue that a human approves via an interactive CLI modelled on `analysis/adjudicate.py`. Provenance is an additive block on existing `data/manifest.json` entries, so every downstream analysis module keeps working untouched.

**Tech Stack:** Python ≥3.12, stdlib only (`json`, `pathlib`, `dataclasses`, `hashlib`, `argparse`). pytest + ruff. No new runtime dependencies in this plan.

**Spec:** [`docs/superpowers/specs/2026-08-13-corpus-ingest-design.md`](../specs/2026-08-13-corpus-ingest-design.md)

## Global Constraints

- **Python ≥3.12**, interpreter is `.venv/bin/python`. Never use bare `python`.
- **Zero new runtime dependencies.** This plan is stdlib-only. `pdf/epub/docx/OCR/Whisper` belong to roadmap #32–37 and the future `ingest` extra — do not add them here.
- **ruff line-length 100**, target `py312`, lint rules `E,F,I` (import sorting enforced).
- **`make verify`** (ruff on `tests/` + full pytest + dashboard smoke build) is the gate. Must be green before every commit.
- **Offline only.** No network, no conductor, no LLM calls anywhere in this plan.
- **No real family content in git.** All fixtures are synthetic and written by the test itself into `tmp_path`.
- **Provenance block is named `provenance`**, never `source` — `data/raw/*.json` already uses `source` for the acquisition channel.
- Manifest shape is `{"last_updated": str, "total_articles": int, "articles": [...]}`.

---

### Task 1: Provenance vocabulary and defaults

**Files:**
- Create: `ingest/__init__.py`
- Create: `ingest/provenance.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MODALITIES: frozenset[str]`, `AUTHORSHIPS: frozenset[str]`, `PRIVACIES: frozenset[str]`, `LICENSES: frozenset[str]`, `DATE_CONFIDENCES: frozenset[str]`
  - `default_provenance(**overrides) -> dict` — raises `ValueError` on an unknown vocabulary value.

- [ ] **Step 1: Write the failing test**

Create `tests/test_provenance.py`:

```python
"""Tests for ingest/provenance.py — the provenance vocabulary and defaults."""

import pytest

from ingest.provenance import (
    AUTHORSHIPS,
    MODALITIES,
    default_provenance,
)


class TestDefaultProvenance:
    def test_defaults_are_private_and_george(self):
        prov = default_provenance()
        assert prov["authorship"] == "george"
        assert prov["privacy"] == "private"
        assert prov["date_confidence"] == "unknown"

    def test_every_required_key_is_present(self):
        prov = default_provenance()
        assert set(prov) == {
            "source_id",
            "modality",
            "authorship",
            "privacy",
            "license",
            "acquisition",
            "date_confidence",
        }

    def test_acquisition_has_method_ref_and_at(self):
        prov = default_provenance()
        assert set(prov["acquisition"]) == {"method", "ref", "at"}

    def test_overrides_are_applied(self):
        prov = default_provenance(modality="book", privacy="public")
        assert prov["modality"] == "book"
        assert prov["privacy"] == "public"

    def test_unknown_modality_raises(self):
        with pytest.raises(ValueError, match="modality"):
            default_provenance(modality="hieroglyph")

    def test_unknown_authorship_raises(self):
        with pytest.raises(ValueError, match="authorship"):
            default_provenance(authorship="ghostwriter")

    def test_vocabularies_are_closed(self):
        assert "article" in MODALITIES and "book" in MODALITIES
        assert AUTHORSHIPS == frozenset({"george", "mixed", "other"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest'`

- [ ] **Step 3: Write minimal implementation**

Create `ingest/__init__.py` (empty file).

Create `ingest/provenance.py`:

```python
"""Provenance vocabulary for corpus items (roadmap #29).

A corpus entry's ``provenance`` block records *what a thing is and how we got it*, so a
private letter and a published column are never mistaken for the same kind of evidence.

Named ``provenance``, not ``source``: ``data/raw/*.json`` already uses ``source`` for the
acquisition channel (``wayback`` / ``playwright``).
"""

from datetime import date as _date

MODALITIES = frozenset(
    {"article", "book", "course", "letter", "email", "message", "talk", "post"}
)
AUTHORSHIPS = frozenset({"george", "mixed", "other"})
PRIVACIES = frozenset({"public", "private"})
LICENSES = frozenset({"forbes", "owned", "purchased", "personal"})
DATE_CONFIDENCES = frozenset({"exact", "approximate", "unknown"})

_VOCABULARIES = {
    "modality": MODALITIES,
    "authorship": AUTHORSHIPS,
    "privacy": PRIVACIES,
    "license": LICENSES,
    "date_confidence": DATE_CONFIDENCES,
}


def default_provenance(**overrides) -> dict:
    """Build a provenance block, private-by-default, validating every vocabulary field.

    Defaults are the safe reading of an unknown item: it is his writing, it is private,
    and we do not trust its date until a human says otherwise.
    """
    prov = {
        "source_id": "",
        "modality": "article",
        "authorship": "george",
        "privacy": "private",
        "license": "personal",
        "acquisition": {"method": "ingest", "ref": "", "at": _date.today().isoformat()},
        "date_confidence": "unknown",
    }
    for key, value in overrides.items():
        if key not in prov:
            raise ValueError(f"unknown provenance field: {key!r}")
        vocabulary = _VOCABULARIES.get(key)
        if vocabulary is not None and value not in vocabulary:
            raise ValueError(
                f"invalid {key}: {value!r} — expected one of {sorted(vocabulary)}"
            )
        prov[key] = value
    return prov
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provenance.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the package to setuptools and verify**

Modify `pyproject.toml`, in `[tool.setuptools.packages.find]`:

```toml
include = ["scraper*", "analysis*", "viz*", "training*", "ingest*"]
```

Run: `make verify`
Expected: ruff clean, all tests pass, dashboard builds.

- [ ] **Step 6: Commit**

```bash
git add ingest/__init__.py ingest/provenance.py tests/test_provenance.py pyproject.toml
git commit -m "feat(ingest): provenance vocabulary + private-by-default block (#29)"
```

---

### Task 2: Migrate the existing manifest

**Files:**
- Modify: `ingest/provenance.py` (add `migrate_articles`)
- Modify: `tests/test_provenance.py` (add `TestMigrateArticles`)
- Modify: `data/manifest.json` (data change, committed)

**Interfaces:**
- Consumes: `default_provenance` from Task 1.
- Produces: `migrate_articles(articles: list[dict]) -> tuple[list[dict], int]` — returns `(articles, migrated_count)`. Mirrors `scraper.manifest_dedup.backfill_hashes`'s shape deliberately.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_provenance.py`:

```python
from ingest.provenance import migrate_articles


class TestMigrateArticles:
    def test_scraped_article_gets_forbes_provenance(self):
        articles = [{"slug": "a", "url": "https://forbes.com/x", "title": "A"}]
        out, count = migrate_articles(articles)
        assert count == 1
        prov = out[0]["provenance"]
        assert prov["modality"] == "article"
        assert prov["authorship"] == "george"
        assert prov["privacy"] == "public"
        assert prov["license"] == "forbes"
        assert prov["date_confidence"] == "exact"
        assert prov["acquisition"]["method"] == "scrape"

    def test_source_id_comes_from_slug(self):
        out, _ = migrate_articles([{"slug": "why-the-fed-blinked"}])
        assert out[0]["provenance"]["source_id"] == "why-the-fed-blinked"

    def test_acquisition_ref_is_the_url(self):
        out, _ = migrate_articles([{"slug": "a", "url": "https://forbes.com/x"}])
        assert out[0]["provenance"]["acquisition"]["ref"] == "https://forbes.com/x"

    def test_is_idempotent(self):
        articles = [{"slug": "a", "url": "u"}]
        once, first = migrate_articles(articles)
        twice, second = migrate_articles(once)
        assert first == 1
        assert second == 0
        assert once == twice

    def test_does_not_mutate_input(self):
        articles = [{"slug": "a"}]
        migrate_articles(articles)
        assert "provenance" not in articles[0]

    def test_preserves_existing_fields(self):
        out, _ = migrate_articles([{"slug": "a", "word_count": 42, "tags": ["fed"]}])
        assert out[0]["word_count"] == 42
        assert out[0]["tags"] == ["fed"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provenance.py::TestMigrateArticles -v`
Expected: FAIL — `ImportError: cannot import name 'migrate_articles'`

- [ ] **Step 3: Write minimal implementation**

Append to `ingest/provenance.py`:

```python
def migrate_articles(articles: list[dict]) -> tuple[list[dict], int]:
    """Add a ``provenance`` block to scraped Forbes articles that lack one.

    Pure and offline: takes and returns article dicts, never touches disk. Idempotent —
    entries that already carry ``provenance`` pass through untouched. Returns
    ``(articles, migrated_count)``.
    """
    migrated = 0
    out: list[dict] = []
    for entry in articles:
        if not entry.get("provenance"):
            entry = {
                **entry,
                "provenance": default_provenance(
                    source_id=entry.get("slug", ""),
                    modality="article",
                    authorship="george",
                    privacy="public",
                    license="forbes",
                    acquisition={
                        "method": "scrape",
                        "ref": entry.get("url", ""),
                        "at": entry.get("date", ""),
                    },
                    date_confidence="exact",
                ),
            }
            migrated += 1
        out.append(entry)
    return out, migrated
```

Note: `acquisition` is not in `_VOCABULARIES`, so it passes validation as a plain override.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provenance.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Backfill content hashes on the real manifest**

> **DEVIATION (2026-08-16): steps 5–6 are deferred; this task lands code-only.**
> Three facts discovered at execution time, none true when the plan was written:
> 1. The manifest is now **203 entries with 23 duplicate-slug groups** — the corruption
>    PR #77 addresses. It fixes this at the *read* layer, so the file stays duplicated.
> 2. `data/manifest.json` carries **uncommitted local changes**: 4 genuinely new articles
>    from a scrape at 2026-08-16T07:55Z. Rewriting the file would drag another process's
>    output into this code PR.
> 3. The flag is `--backfill-hashes`, not `--backfill`, and `--apply` also **collapses the
>    23 duplicate groups** — a substantive corpus change well outside this task's scope.
>
> `migrate_articles` is idempotent, so the one-time data migration costs nothing to defer.
> Apply it after #77 lands and the new articles are committed, then commit that diff alone.

Original steps, to run later:

Only 31 of 199 entries carried a `content_hash`; dedup in Task 4 depends on it.

Run: `.venv/bin/python -m scraper.manifest_dedup --apply --in-place --backfill-hashes`

Then verify:

```bash
.venv/bin/python -c "
import json; a=json.load(open('data/manifest.json'))['articles']
print('with content_hash:', sum('content_hash' in e for e in a), '/', len(a))"
```

Expected: a number much closer to 199 than 31. Some entries may still lack a hash if their raw body is missing from disk — that is acceptable and expected.

- [ ] **Step 6: Migrate the real manifest**

Run:

```bash
.venv/bin/python -c "
import json
from pathlib import Path
from ingest.provenance import migrate_articles
p = Path('data/manifest.json')
m = json.loads(p.read_text())
m['articles'], n = migrate_articles(m['articles'])
p.write_text(json.dumps(m, indent=2) + '\n')
print('migrated', n, 'entries')"
```

Expected: `migrated 199 entries`

Verify idempotency by running the exact same command again.
Expected: `migrated 0 entries`

- [ ] **Step 7: Verify and commit**

Run: `make verify`
Expected: green.

```bash
git add ingest/provenance.py tests/test_provenance.py data/manifest.json
git commit -m "feat(ingest): migrate 199 manifest entries to provenance + backfill hashes (#29)"
```

---

### Task 3: Handler registry and the plaintext handler

**Files:**
- Create: `ingest/extract.py`
- Create: `ingest/handlers/__init__.py`
- Create: `ingest/handlers/plaintext.py`
- Test: `tests/test_ingest_handlers.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ExtractResult` — frozen dataclass with fields `documents: list[dict]`, `meta: dict`, `confidence: float`, `warnings: list[str]`. Each document is `{"title": str, "text": str, "ordinal": int}`.
  - `register(*extensions)` — decorator registering a handler.
  - `handler_for(path: Path) -> Callable[[Path], ExtractResult] | None`
  - `extract(path: Path) -> ExtractResult` — raises `UnsupportedFormat` when no handler matches.
  - `UnsupportedFormat(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_handlers.py`:

```python
"""Tests for the ingest handler registry and the stdlib plaintext handler (roadmap #30)."""

import pytest

from ingest.extract import ExtractResult, UnsupportedFormat, extract, handler_for


class TestRegistry:
    def test_txt_and_md_have_a_handler(self, tmp_path):
        assert handler_for(tmp_path / "a.txt") is not None
        assert handler_for(tmp_path / "a.md") is not None

    def test_extension_match_is_case_insensitive(self, tmp_path):
        assert handler_for(tmp_path / "A.TXT") is not None

    def test_unknown_extension_has_no_handler(self, tmp_path):
        assert handler_for(tmp_path / "a.wav") is None

    def test_extract_raises_on_unsupported_format(self, tmp_path):
        path = tmp_path / "a.wav"
        path.write_bytes(b"\x00")
        with pytest.raises(UnsupportedFormat, match=".wav"):
            extract(path)


class TestPlaintextHandler:
    def test_returns_one_document_with_the_file_text(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("The Fed blinked.\nAgain.\n")
        result = extract(path)
        assert isinstance(result, ExtractResult)
        assert len(result.documents) == 1
        assert "The Fed blinked." in result.documents[0]["text"]
        assert result.documents[0]["ordinal"] == 0

    def test_title_falls_back_to_the_filename_stem(self, tmp_path):
        path = tmp_path / "fed-note.txt"
        path.write_text("body")
        assert extract(path).meta["title"] == "fed-note"

    def test_markdown_h1_becomes_the_title(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("# On Central Banking\n\nBody text.\n")
        assert extract(path).meta["title"] == "On Central Banking"

    def test_plaintext_is_high_confidence_with_no_warnings(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("body")
        result = extract(path)
        assert result.confidence == 1.0
        assert result.warnings == []

    def test_empty_file_warns_and_drops_confidence(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("   \n")
        result = extract(path)
        assert result.confidence == 0.0
        assert any("empty" in w.lower() for w in result.warnings)

    def test_meta_carries_no_date_for_plaintext(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("body")
        result = extract(path)
        assert result.meta["date"] == ""
        assert result.meta["date_confidence"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ingest_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.extract'`

- [ ] **Step 3: Write the registry**

Create `ingest/extract.py`:

```python
"""Extraction contract and handler registry (roadmap #30).

A handler is a **pure function** ``(Path) -> ExtractResult``: no network, no mutation of
its input, deterministic for a given file. That keeps every format trivially testable and
safe for the unattended nightly agent.

Adding a format is an isolated change: a new module under ``ingest/handlers/`` with a
``@register(...)`` decorator, plus its import in ``ingest/handlers/__init__.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class UnsupportedFormat(Exception):
    """No handler is registered for this file extension."""


@dataclass(frozen=True)
class ExtractResult:
    """What a handler recovered from one file.

    ``documents`` is the unit of *analysis* — a book yields one per chapter, an mbox one
    per message — each ``{"title": str, "text": str, "ordinal": int}``. ``meta`` describes
    the *source* as a whole. ``confidence`` is 0.0-1.0; ``warnings`` are human-readable
    strings surfaced first in review.
    """

    documents: list[dict]
    meta: dict
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)


HANDLERS: dict[str, Callable[[Path], ExtractResult]] = {}


def register(*extensions: str):
    """Register a handler for one or more lowercase extensions (including the dot)."""

    def decorator(func: Callable[[Path], ExtractResult]):
        for ext in extensions:
            HANDLERS[ext.lower()] = func
        return func

    return decorator


def handler_for(path: Path) -> Callable[[Path], ExtractResult] | None:
    """Return the handler for ``path``'s extension, or None if unsupported."""
    return HANDLERS.get(Path(path).suffix.lower())


def extract(path: Path) -> ExtractResult:
    """Run the registered handler for ``path``.

    Raises ``UnsupportedFormat`` if no handler matches — callers stage that as a skipped
    file rather than failing the whole run.
    """
    path = Path(path)
    handler = handler_for(path)
    if handler is None:
        raise UnsupportedFormat(f"no handler for {path.suffix or '(no extension)'}")
    return handler(path)


def empty_meta(title: str = "") -> dict:
    """The meta block a handler starts from, matching the provenance vocabulary."""
    return {
        "title": title,
        "date": "",
        "date_confidence": "unknown",
        "modality": "letter",
        "authorship": "george",
        "privacy": "private",
        "license": "personal",
    }
```

- [ ] **Step 4: Write the plaintext handler**

Create `ingest/handlers/plaintext.py`:

```python
"""Plaintext and Markdown handler — stdlib only (roadmap #30)."""

from pathlib import Path

from ingest.extract import ExtractResult, empty_meta, register


@register(".txt", ".md")
def extract_plaintext(path: Path) -> ExtractResult:
    """Read a text file as a single document.

    A Markdown ``# H1`` on the first non-blank line becomes the title; otherwise the
    filename stem is used. An effectively-empty file is surfaced as a warning at zero
    confidence rather than silently entering the queue.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()

    title = Path(path).stem
    for line in stripped.splitlines():
        if line.strip():
            if line.lstrip().startswith("# "):
                title = line.lstrip()[2:].strip()
            break

    meta = empty_meta(title)
    if not stripped:
        return ExtractResult(
            documents=[], meta=meta, confidence=0.0, warnings=["file is empty"]
        )

    return ExtractResult(
        documents=[{"title": title, "text": text, "ordinal": 0}],
        meta=meta,
        confidence=1.0,
        warnings=[],
    )
```

Create `ingest/handlers/__init__.py`:

```python
"""Handler package. Importing a module here is what registers its formats."""

from ingest.handlers import plaintext  # noqa: F401  (import registers .txt/.md)
```

Add this import to the bottom of `ingest/extract.py` so the registry is populated on use:

```python
# Populate the registry. Kept at the bottom to avoid a circular import: handlers import
# `register` from this module.
from ingest import handlers  # noqa: E402,F401
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ingest_handlers.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Verify and commit**

Run: `make verify`
Expected: green.

```bash
git add ingest/extract.py ingest/handlers/ tests/test_ingest_handlers.py
git commit -m "feat(ingest): pure-function handler registry + plaintext handler (#30)"
```

---

### Task 4: Queue staging and the `make ingest` command

**Files:**
- Create: `ingest/queue.py`
- Create: `ingest/__main__.py`
- Test: `tests/test_ingest_queue.py`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `extract`, `UnsupportedFormat`, `ExtractResult` (Task 3); `default_provenance` (Task 1).
- Produces:
  - `stage_file(path: Path, queue_dir: Path) -> dict | None` — returns the staged item, or `None` if unsupported or a duplicate.
  - `load_queue(queue_dir: Path) -> list[dict]` — sorted by `id`.
  - `save_item(item: dict, queue_dir: Path) -> Path`
  - `scan_inbox(inbox: Path, queue_dir: Path) -> dict` — returns `{"staged": int, "skipped": int, "duplicates": int}`.
  - Queue item keys: `id`, `status` (`pending`/`accepted`/`rejected`), `original`, `content_hash`, `documents`, `meta`, `confidence`, `warnings`, `staged_at`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_queue.py`:

```python
"""Tests for ingest queue staging (roadmap #30)."""

from ingest.queue import load_queue, scan_inbox, stage_file


def _inbox_with(tmp_path, name: str, text: str):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / name).write_text(text)
    return inbox


class TestStageFile:
    def test_staged_item_is_pending_with_content_hash(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        item = stage_file(inbox / "a.txt", queue)
        assert item["status"] == "pending"
        assert item["content_hash"]
        assert item["original"].endswith("a.txt")

    def test_staged_item_is_written_to_disk(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        stage_file(inbox / "a.txt", queue)
        assert len(list(queue.glob("*.json"))) == 1

    def test_unsupported_format_returns_none_and_stages_nothing(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "a.wav").write_bytes(b"\x00")
        queue = tmp_path / "queue"
        assert stage_file(inbox / "a.wav", queue) is None
        assert not list(queue.glob("*.json"))

    def test_restaging_the_same_content_is_a_no_op(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        queue = tmp_path / "queue"
        stage_file(inbox / "a.txt", queue)
        assert stage_file(inbox / "a.txt", queue) is None
        assert len(list(queue.glob("*.json"))) == 1

    def test_item_carries_documents_and_warnings(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "body")
        item = stage_file(inbox / "a.txt", tmp_path / "queue")
        assert item["documents"][0]["text"] == "body"
        assert item["warnings"] == []


class TestScanInbox:
    def test_counts_staged_skipped_and_duplicates(self, tmp_path):
        inbox = _inbox_with(tmp_path, "a.txt", "one")
        (inbox / "b.md").write_text("# Two\n\ntwo")
        (inbox / "c.wav").write_bytes(b"\x00")
        queue = tmp_path / "queue"

        first = scan_inbox(inbox, queue)
        assert first["staged"] == 2
        assert first["skipped"] == 1

        second = scan_inbox(inbox, queue)
        assert second["staged"] == 0
        assert second["duplicates"] == 2

    def test_missing_inbox_is_not_an_error(self, tmp_path):
        result = scan_inbox(tmp_path / "nope", tmp_path / "queue")
        assert result == {"staged": 0, "skipped": 0, "duplicates": 0}


class TestLoadQueue:
    def test_returns_items_sorted_by_id(self, tmp_path):
        inbox = _inbox_with(tmp_path, "b.txt", "two")
        (inbox / "a.txt").write_text("one")
        queue = tmp_path / "queue"
        scan_inbox(inbox, queue)
        ids = [item["id"] for item in load_queue(queue)]
        assert ids == sorted(ids)

    def test_empty_queue_dir_returns_empty_list(self, tmp_path):
        assert load_queue(tmp_path / "queue") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ingest_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.queue'`

- [ ] **Step 3: Write the implementation**

Create `ingest/queue.py`:

```python
"""Stage extracted files into a review queue (roadmap #30).

Extraction never touches the corpus. Everything lands here as pending JSON until a human
accepts it in ``ingest.review``. Re-dropping a file is a no-op: de-duplication reuses the
scraper's ``content_hash`` convention (MD5 of body).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.extract import UnsupportedFormat, extract
from scraper.manifest_dedup import content_hash_for

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INBOX_DIR = DATA_DIR / "inbox"
QUEUE_DIR = DATA_DIR / "ingest" / "queue"


def load_queue(queue_dir: Path = QUEUE_DIR) -> list[dict]:
    """Read every queue item, sorted by id. A missing directory is an empty queue."""
    queue_dir = Path(queue_dir)
    if not queue_dir.is_dir():
        return []
    items = [json.loads(p.read_text()) for p in queue_dir.glob("*.json")]
    return sorted(items, key=lambda item: item.get("id", ""))


def save_item(item: dict, queue_dir: Path = QUEUE_DIR) -> Path:
    """Write one queue item, creating the queue directory if needed."""
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{item['id']}.json"
    path.write_text(json.dumps(item, indent=2) + "\n")
    return path


def _combined_text(result) -> str:
    return "\n".join(doc.get("text", "") for doc in result.documents)


def stage_file(path: Path, queue_dir: Path = QUEUE_DIR) -> dict | None:
    """Extract one file into the queue.

    Returns the staged item, or ``None`` when the format is unsupported or the content is
    already queued. Never raises on an unsupported file — a mixed inbox must not fail the
    whole run.
    """
    path = Path(path)
    try:
        result = extract(path)
    except UnsupportedFormat:
        return None

    content_hash = content_hash_for(_combined_text(result))
    existing = {item.get("content_hash") for item in load_queue(queue_dir)}
    if content_hash in existing:
        return None

    item = {
        "id": f"{path.stem}-{content_hash[:8]}",
        "status": "pending",
        "original": str(path),
        "content_hash": content_hash,
        "documents": result.documents,
        "meta": result.meta,
        "confidence": result.confidence,
        "warnings": result.warnings,
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_item(item, queue_dir)
    return item


def scan_inbox(inbox: Path = INBOX_DIR, queue_dir: Path = QUEUE_DIR) -> dict:
    """Stage every file in ``inbox``. Returns counts of staged / skipped / duplicates."""
    inbox = Path(inbox)
    counts = {"staged": 0, "skipped": 0, "duplicates": 0}
    if not inbox.is_dir():
        return counts

    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        from ingest.extract import handler_for

        if handler_for(path) is None:
            counts["skipped"] += 1
            continue
        if stage_file(path, queue_dir) is None:
            counts["duplicates"] += 1
        else:
            counts["staged"] += 1
    return counts
```

Create `ingest/__main__.py`:

```python
"""``make ingest`` — scan data/inbox/ and stage everything for review."""

import argparse
from pathlib import Path

from ingest.queue import INBOX_DIR, QUEUE_DIR, scan_inbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description="Extract files from data/inbox/ into the review queue. "
        "Never modifies the corpus — run `make ingest-review` to accept items.",
    )
    parser.add_argument("--inbox", type=Path, default=INBOX_DIR)
    parser.add_argument("--queue", type=Path, default=QUEUE_DIR)
    args = parser.parse_args(argv)

    counts = scan_inbox(args.inbox, args.queue)
    print(
        f"Staged {counts['staged']}, skipped {counts['skipped']} (unsupported), "
        f"{counts['duplicates']} already queued."
    )
    if counts["staged"]:
        print("Review them with: make ingest-review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ingest_queue.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Wire up Makefile and gitignore**

Add to `.gitignore`:

```
data/inbox/
data/ingest/
```

Add to `Makefile` (near the other analysis targets):

```make
ingest:
	$(PYTHON) -m ingest $(ARGS)
```

- [ ] **Step 6: Smoke-test end to end**

```bash
mkdir -p data/inbox && printf '# Test Note\n\nA line he wrote.\n' > data/inbox/test-note.md
make ingest
```

Expected: `Staged 1, skipped 0 (unsupported), 0 already queued.`

Run `make ingest` again.
Expected: `Staged 0, skipped 0 (unsupported), 1 already queued.`

Clean up: `rm -rf data/inbox data/ingest`

- [ ] **Step 7: Verify and commit**

Run: `make verify`
Expected: green.

```bash
git add ingest/queue.py ingest/__main__.py tests/test_ingest_queue.py Makefile .gitignore
git commit -m "feat(ingest): inbox scan + dedup'd review queue + make ingest (#30)"
```

---

### Task 5: The review CLI

**Files:**
- Create: `ingest/review.py`
- Test: `tests/test_ingest_review.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `load_queue`, `save_item`, `QUEUE_DIR` (Task 4); `default_provenance`, vocabularies (Task 1).
- Produces:
  - `queue_summary(items: list[dict]) -> dict` — `{"total", "pending", "accepted", "rejected"}`
  - `print_report(items: list[dict]) -> None`
  - `accept_item(item: dict, manifest: dict) -> dict` — appends a manifest entry, marks the item accepted, returns the manifest.
  - `run_cli(queue_dir=QUEUE_DIR, manifest_path=..., limit=None, input_fn=input) -> int`

`input_fn` is an injected seam so the loop is testable without a TTY — the same style as `backfill_hashes`'s `read_body`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_review.py`:

```python
"""Tests for the ingest review CLI (roadmap #31)."""

import json

from ingest.queue import save_item
from ingest.review import accept_item, queue_summary, run_cli


def _item(item_id="a-1234abcd", status="pending"):
    return {
        "id": item_id,
        "status": status,
        "original": "data/inbox/a.txt",
        "content_hash": "1234abcd",
        "documents": [{"title": "A", "text": "body", "ordinal": 0}],
        "meta": {
            "title": "A",
            "date": "",
            "date_confidence": "unknown",
            "modality": "letter",
            "authorship": "george",
            "privacy": "private",
            "license": "personal",
        },
        "confidence": 1.0,
        "warnings": [],
        "staged_at": "2026-08-13T00:00:00+00:00",
    }


def _scripted(answers):
    """An input() stand-in that replays a fixed list of answers."""
    it = iter(answers)

    def _fn(_prompt=""):
        return next(it, "q")

    return _fn


class TestQueueSummary:
    def test_counts_by_status(self):
        items = [_item("a"), _item("b", "accepted"), _item("c", "rejected")]
        assert queue_summary(items) == {
            "total": 3,
            "pending": 1,
            "accepted": 1,
            "rejected": 1,
        }


class TestAcceptItem:
    def test_appends_a_manifest_entry_with_provenance(self):
        manifest = {"last_updated": "", "total_articles": 0, "articles": []}
        out = accept_item(_item(), manifest)
        assert len(out["articles"]) == 1
        prov = out["articles"][0]["provenance"]
        assert prov["modality"] == "letter"
        assert prov["privacy"] == "private"
        assert prov["acquisition"]["method"] == "ingest"

    def test_updates_total_articles(self):
        manifest = {"last_updated": "", "total_articles": 0, "articles": []}
        out = accept_item(_item(), manifest)
        assert out["total_articles"] == 1

    def test_marks_the_item_accepted(self):
        item = _item()
        accept_item(item, {"last_updated": "", "total_articles": 0, "articles": []})
        assert item["status"] == "accepted"


class TestRunCli:
    def test_accepting_writes_the_manifest_and_updates_the_item(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"last_updated": "", "total_articles": 0, "articles": []})
        )

        rc = run_cli(
            queue_dir=queue, manifest_path=manifest_path, input_fn=_scripted(["a"])
        )

        assert rc == 0
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest["articles"]) == 1
        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "accepted"

    def test_rejecting_marks_rejected_and_leaves_manifest_alone(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"last_updated": "", "total_articles": 0, "articles": []})
        )

        run_cli(
            queue_dir=queue,
            manifest_path=manifest_path,
            input_fn=_scripted(["r", "bad scan"]),
        )

        item = json.loads((queue / "a-1234abcd.json").read_text())
        assert item["status"] == "rejected"
        assert item["reject_reason"] == "bad scan"
        assert json.loads(manifest_path.read_text())["articles"] == []

    def test_quitting_leaves_the_item_pending(self, tmp_path):
        queue = tmp_path / "queue"
        save_item(_item(), queue)
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"last_updated": "", "total_articles": 0, "articles": []})
        )

        run_cli(queue_dir=queue, manifest_path=manifest_path, input_fn=_scripted(["q"]))

        assert json.loads((queue / "a-1234abcd.json").read_text())["status"] == "pending"

    def test_empty_queue_returns_zero(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"last_updated": "", "total_articles": 0, "articles": []})
        )
        assert run_cli(queue_dir=tmp_path / "queue", manifest_path=manifest_path) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ingest_review.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.review'`

- [ ] **Step 3: Write the implementation**

Create `ingest/review.py`:

```python
"""Interactive review of the ingest queue (roadmap #31).

Mirrors ``analysis/adjudicate.py``: iterate unreviewed items, prompt, write the decision
back immediately so progress survives a Ctrl-C.

Two rules make this usable rather than tedious:
  * Review is per **source**, not per document — a book prompts once, not forty times.
  * Rejects are never deleted; they keep their reason so a bad extraction is recoverable.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from ingest.provenance import (
    AUTHORSHIPS,
    MODALITIES,
    PRIVACIES,
    default_provenance,
)
from ingest.queue import QUEUE_DIR, load_queue, save_item

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "manifest.json"


def queue_summary(items: list[dict]) -> dict:
    """Count queue items by status."""
    return {
        "total": len(items),
        "pending": sum(i.get("status") == "pending" for i in items),
        "accepted": sum(i.get("status") == "accepted" for i in items),
        "rejected": sum(i.get("status") == "rejected" for i in items),
    }


def print_report(items: list[dict]) -> None:
    """Print a queue summary. Read-only — safe for the nightly agent to run."""
    summary = queue_summary(items)
    print(
        f"Queue: {summary['total']} item(s) — {summary['pending']} pending, "
        f"{summary['accepted']} accepted, {summary['rejected']} rejected."
    )
    for item in items:
        if item.get("status") != "pending":
            continue
        warn = f"  ⚠ {len(item['warnings'])}" if item.get("warnings") else ""
        print(
            f"  [{item.get('confidence', 0):.2f}] {item['id']}  "
            f"{item['meta'].get('title', '(untitled)')[:48]}{warn}"
        )


def accept_item(item: dict, manifest: dict) -> dict:
    """Append one accepted queue item to the manifest as a document entry."""
    meta = item["meta"]
    provenance = default_provenance(
        source_id=item["id"],
        modality=meta.get("modality", "letter"),
        authorship=meta.get("authorship", "george"),
        privacy=meta.get("privacy", "private"),
        license=meta.get("license", "personal"),
        acquisition={
            "method": "ingest",
            "ref": item.get("original", ""),
            "at": date.today().isoformat(),
        },
        date_confidence=meta.get("date_confidence", "unknown"),
    )
    word_count = sum(len(doc.get("text", "").split()) for doc in item["documents"])
    manifest.setdefault("articles", []).append(
        {
            "slug": item["id"],
            "title": meta.get("title", ""),
            "date": meta.get("date", ""),
            "url": "",
            "tags": [],
            "word_count": word_count,
            "content_hash": item.get("content_hash", ""),
            "provenance": provenance,
        }
    )
    manifest["total_articles"] = len(manifest["articles"])
    item["status"] = "accepted"
    return manifest


def _show(item: dict) -> None:
    meta = item["meta"]
    print("\n" + "=" * 72)
    for warning in item.get("warnings", []):
        print(f"  ⚠  {warning}")
    print(f"  {item['id']}   confidence {item.get('confidence', 0):.2f}")
    print(f"  TITLE:      {meta.get('title', '(untitled)')}")
    print(f"  DATE:       {meta.get('date') or '—'} ({meta.get('date_confidence')})")
    print(f"  MODALITY:   {meta.get('modality')}   AUTHORSHIP: {meta.get('authorship')}")
    print(f"  PRIVACY:    {meta.get('privacy')}   DOCUMENTS: {len(item['documents'])}")
    preview = (item["documents"][0]["text"] if item["documents"] else "")[:400]
    print("-" * 72)
    print("  " + preview.replace("\n", "\n  "))
    print("-" * 72)
    print(f"  original: file://{item.get('original', '')}")
    print("  [a]ccept  [e]dit  [r]eject   ([s]kip / [q]uit)")


def _edit(item: dict, input_fn) -> None:
    """Correct the fields worth correcting. Blank input keeps the current value."""
    meta = item["meta"]
    for field_name, vocabulary in (
        ("title", None),
        ("date", None),
        ("modality", MODALITIES),
        ("authorship", AUTHORSHIPS),
        ("privacy", PRIVACIES),
    ):
        hint = f" {sorted(vocabulary)}" if vocabulary else ""
        answer = input_fn(f"  {field_name}{hint} [{meta.get(field_name, '')}]> ").strip()
        if not answer:
            continue
        if vocabulary and answer not in vocabulary:
            print(f"  ! '{answer}' is not valid — keeping {meta.get(field_name)!r}")
            continue
        meta[field_name] = answer
        if field_name == "date":
            meta["date_confidence"] = "approximate"


def run_cli(
    queue_dir: Path = QUEUE_DIR,
    manifest_path: Path = MANIFEST_PATH,
    limit: int | None = None,
    input_fn=input,
) -> int:
    """Interactive review loop. Writes after every decision so progress is resumable."""
    queue_dir = Path(queue_dir)
    manifest_path = Path(manifest_path)
    items = load_queue(queue_dir)
    if not items:
        print("Queue is empty. Drop files in data/inbox/ and run `make ingest`.")
        return 0

    manifest = json.loads(manifest_path.read_text())
    summary = queue_summary(items)
    print(f"Loaded {summary['total']} item(s) — {summary['pending']} pending.")

    done = 0
    for item in items:
        if item.get("status") != "pending":
            continue
        if limit is not None and done >= limit:
            print(f"\nReached limit of {limit}. Stopping.")
            break

        _show(item)
        choice = input_fn("  decision> ").strip().lower()

        if choice in ("q", "quit"):
            break
        if choice in ("s", "skip", ""):
            continue
        if choice in ("e", "edit"):
            _edit(item, input_fn)
            choice = input_fn("  decision> ").strip().lower()
        if choice in ("r", "reject"):
            item["status"] = "rejected"
            item["reject_reason"] = input_fn("  reason> ").strip()
            save_item(item, queue_dir)
            print("  ✓ rejected")
            done += 1
            continue
        if choice in ("a", "accept"):
            accept_item(item, manifest)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            save_item(item, queue_dir)
            print("  ✓ accepted")
            done += 1
            continue
        print(f"  ! '{choice}' is not a decision — skipping.")

    print(f"\nDone. {done} decision(s) this session.")
    print_report(load_queue(queue_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.review",
        description="Review staged ingest items and accept them into the corpus.",
    )
    parser.add_argument("--queue", type=Path, default=QUEUE_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the queue summary and exit. Read-only; changes nothing.",
    )
    args = parser.parse_args(argv)

    if args.report:
        print_report(load_queue(args.queue))
        return 0
    return run_cli(queue_dir=args.queue, manifest_path=args.manifest, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ingest_review.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Add the Makefile target**

Add to `Makefile`:

```make
ingest-review:
	$(PYTHON) -m ingest.review $(ARGS)
```

- [ ] **Step 6: Smoke-test the whole slice end to end**

```bash
mkdir -p data/inbox && printf '# A Letter\n\nDear Will,\n\nThe Fed blinked again.\n' > data/inbox/letter.md
make ingest
make ingest-review ARGS=--report
```

Expected: report shows 1 pending item.

Then run `make ingest-review`, press `a`, and confirm the manifest grew:

```bash
.venv/bin/python -c "
import json; m=json.load(open('data/manifest.json'))
print('total:', m['total_articles'], '| last:', m['articles'][-1]['slug'])"
```

Expected: total is 200, last slug starts with `letter-`.

**Then undo the smoke test** so the committed manifest stays at 199:

```bash
git checkout -- data/manifest.json
rm -rf data/inbox data/ingest
```

- [ ] **Step 7: Verify and commit**

Run: `make verify`
Expected: green.

```bash
git add ingest/review.py tests/test_ingest_review.py Makefile
git commit -m "feat(ingest): interactive review CLI + --report (#31)"
```

---

### Task 6: Roadmap and documentation

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Add the `ingest` category and items to the roadmap**

In `docs/roadmap.md`, add `ingest` to the category list on line 10:

```
`infra · scraper · analysis · ingest · dashboard · training · family · docs`.
```

Add a new section after `## scraper`:

```markdown
## ingest

Corpus II — a reviewed, offline second front door for material beyond Forbes. Design:
[`superpowers/specs/2026-08-13-corpus-ingest-design.md`](superpowers/specs/2026-08-13-corpus-ingest-design.md).
All items are offline, pure, and unattended-safe.

29. **P1 · S · ingest** — `provenance` schema + pure migration of the 199 entries;
    backfill `content_hash`. *(done 2026-08-13)*
30. **P1 · S · ingest** — ingest skeleton: inbox, queue, `make ingest`, handler registry,
    `.txt`/`.md` handler. *(done 2026-08-13)*
31. **P1 · S · ingest** — review CLI, interactive + `--report`. *(done 2026-08-13)*
32. **P2 · S · ingest** — `.eml`/`.mbox` handler (stdlib `email`/`mailbox`; thread split,
    quoted-reply stripping, one document per message).
33. **P2 · S · ingest** — `.docx` handler (first user of the new `ingest` extra).
34. **P2 · M · ingest** — `.pdf` handler + no-text-layer detection (warn and defer to OCR).
35. **P2 · M · ingest** — `.epub` handler + chapter segmentation. Unlocks the books.
36. **P2 · M · ingest** — image OCR handler with a confidence score.
37. **P3 · L · ingest** — audio/video transcription (local Whisper) + timestamped segments.
38. **P2 · S · analysis** — modality-aware analysis defaults (`authorship: george`) and a
    modality breakdown surfaced in the dashboard.
```

Mark 29–31 done only if the earlier tasks actually landed.

- [ ] **Step 2: Note the pipeline in architecture.md**

Add to `docs/architecture.md`, near the scraper description:

```markdown
### Ingest (Corpus II)

A second, human-reviewed path into the corpus for non-Forbes material:

```
data/inbox/ → make ingest → data/ingest/queue/ → make ingest-review → manifest + data/raw/
```

Handlers are pure `(Path) -> ExtractResult` functions registered by extension in
`ingest/handlers/`; adding a format is an isolated change. Extraction never modifies the
corpus — only `ingest-review` does, and only on a human decision. Every entry carries a
`provenance` block (modality, authorship, privacy, license, acquisition) so that a private
letter is never mistaken for a published column. Items default to `privacy: private`.
```

- [ ] **Step 3: Verify and commit**

Run: `make verify`
Expected: green.

```bash
git add docs/roadmap.md docs/architecture.md
git commit -m "docs(ingest): add the ingest roadmap category + architecture note (#29-31)"
```

---

## Self-Review Notes

**Spec coverage:** provenance schema → Task 1; migration + hash backfill → Task 2; one-source-many-documents → `ExtractResult.documents` (Task 3) and `accept_item`'s per-source entry (Task 5); handler registry + dependency policy → Task 3; dedup → Task 4; review CLI incl. per-source review, non-deleting rejects, `--report` → Task 5; testing rules → every task; roadmap items → Task 6.

**Deliberately deferred from this plan** (spec sections that belong to later roadmap items):
- The **T3 private-document guard** in `analysis/conductor.py`. Nothing in this slice makes a conductor call, so the guard has no caller to protect yet. It lands with item #38, the first work that runs analysis over ingested documents. Tracked in the spec's Privacy section.
- **`data/raw/` writing.** Task 5 records documents in the queue item and manifest but does not yet write `data/raw/<id>.json`. Analysis modules read raw bodies, so item #38 must add this. Called out so it is not mistaken for an oversight.
- The `ingest` **extra** in `pyproject.toml` — no dependency needs it until item #33.
