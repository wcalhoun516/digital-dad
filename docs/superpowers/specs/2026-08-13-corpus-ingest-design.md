# Design — Corpus II: provenance model + manual multi-modal ingest

**Date:** 2026-08-13
**Status:** approved (design), pending implementation plan
**Touches:** new `ingest/` package (+ tests), `data/manifest.json` schema (additive),
`scraper/manifest_dedup.py` (reuse), `pyproject.toml` (new `ingest` extra), `Makefile`.
Downstream analysis modules are **unchanged**.

## Goal

Give the archive a **second front door**. Today the only way into the corpus is the Forbes
scraper, which yields uniform, public, text-only articles. This design adds a reviewed,
offline path for heterogeneous material in Dr. Calhoun's own words — books, course materials,
letters, email, messages, talks — and the provenance model that keeps citations trustworthy
once the corpus stops being uniform.

Two parts, designed together because the schema is defined by what the extractors can
actually recover:

- **C1 — provenance model:** describe *what a thing is and how we got it*.
- **C2 — manual ingest:** get files in, extract text, and gate everything behind human review.

Out of scope here: the discovery agent (C3) and the family-facing surface (C4). See
[Deferred](#deferred).

## Context

- The corpus is **199 articles**, 2020–2026, and thinning (45 → 64 → 34 → 21 → 12 → 15 → 6).
  173 of 199 were recovered from Wayback rather than live Forbes.
- The north star is *"evidenced, not hallucinated"* — every in-voice claim citable to something
  he actually wrote. A mixed-modality corpus makes provenance load-bearing rather than
  cosmetic: a private letter and a published column are not the same kind of evidence.
- Core has **zero runtime dependencies**; heavy toolchains live in opt-in extras
  (`scrape`, `analyze`, `finetune`) kept out of `all`. Ingest must honor both conventions.
- `analysis/adjudicate.py` is the established human-in-the-loop pattern: iterate unreviewed
  items, prompt, write decisions back to JSON. The review CLI mirrors it rather than
  inventing a second review surface.

---

## Part 1 — Provenance model (C1)

### Schema

Each `data/manifest.json` entry gains one **additive** `provenance` block. Existing consumers
ignore unknown keys, so nothing downstream breaks.

```json
"provenance": {
  "source_id": "book-quantum-economics",
  "modality": "article|book|course|letter|email|message|talk|post",
  "authorship": "george|mixed|other",
  "privacy": "public|private",
  "license": "forbes|owned|purchased|personal",
  "acquisition": {"method": "scrape|ingest", "ref": "<url or original filename>", "at": "2026-08-14"},
  "date_confidence": "exact|approximate|unknown"
}
```

**Named `provenance`, not `source`.** `data/raw/*.json` already has a top-level `source` key
meaning acquisition channel (`wayback`, `playwright`). Reusing that name would collide.

Field notes:

- **`authorship`** is the field Ask Dad and any voice work must filter on. Only `george`
  is quotable as his thinking. `mixed` (a thread he participates in) is citable context;
  `other` is never put in his voice.
- **`privacy`** drives tier routing (see [Privacy](#privacy-is-enforced-in-code)).
- **`date_confidence`** exists because a scanned letter often has no reliable date. Timeline
  and intellectual-arc views must be able to exclude `unknown` rather than silently plot a
  guess.

### Migration

A pure function migrates the 199 existing entries to
`article / george / public / forbes / method:scrape / date_confidence:exact`. No re-scrape, no
network, fully testable on a fixture manifest. Entries already carrying a `provenance` block
are left untouched (idempotent).

### One source yields many documents

**This is the load-bearing decision.** A source is the *thing you acquired*; a document is the
*unit of analysis*. A book becomes ~40 chapter documents sharing one `source_id`; an mbox
becomes one document per message; a talk becomes one document per transcript segment.

Every downstream module — themes, embeddings, entity graph, Ask Dad — keeps operating on
documents and **requires no changes**. The corpus simply grows.

### No numeric weighting

A book is ~80k words, comparable to the entire current corpus, and will move theme shares and
retrieval. The obvious fix — a numeric `weight` — is rejected: weights are hard to justify,
hard to explain, and bury the distortion inside a constant.

Instead, analyses **filter and group by modality**, defaulting to `authorship: george`, and
report a modality breakdown alongside their results. A book's influence on the numbers becomes
*visible* rather than silently baked in. (Roadmap #38.)

---

## Part 2 — Ingest pipeline (C2)

### Flow

```
data/inbox/                  ← drop files here (gitignored)
      ↓   make ingest              extract only; corpus untouched
data/ingest/queue/<id>.json        text + guessed metadata + confidence + warnings
      ↓   make ingest-review       interactive CLI (mirrors adjudicate.py)
data/raw/<id>.json  +  manifest entry with provenance
```

`data/inbox/`, `data/ingest/` and `data/raw/` are all gitignored. Nothing ingested is ever
committed.

### Handler contract

Each format is a **pure function** registered by extension:

```python
extract(path: Path) -> ExtractResult
# ExtractResult: documents[], meta{title,date,modality,...}, confidence: float, warnings: list[str]
```

Pure means: no network, no mutation of its input, deterministic for a given file. That makes
every handler trivially testable and safe for the unattended nightly agent.

The registry is the point of the design — it turns "support more formats" into a queue of
small, independent, offline PRs, one handler per night.

### Dependency policy

Split along the existing zero-dependency-core line:

| Tier | Formats | Dependency |
|---|---|---|
| **Core (stdlib)** | `.txt`, `.md`, `.eml`, `.mbox` | none — `email` + `mailbox` handle threading and quoted-reply stripping |
| **`ingest` extra** | `.pdf`, `.epub`, `.docx`, images (OCR), audio/video (local Whisper) | opt-in; Whisper carries the `platform_machine == 'arm64'` marker like `finetune` |

A missing dependency yields a clear `install .[ingest]` message and skips that file. It never
crashes the run and never blocks other formats.

### Dedup and idempotency

Reuse the scraper's existing convention: `scraper.manifest_dedup.content_hash_for(body)`
(MD5 of body). Re-dropping the same file is a no-op.

**Prerequisite:** only **31 of 199** manifest entries currently carry a `content_hash`.
`scraper/manifest_dedup.py::backfill_hashes` already exists to fill them from raw bodies on
disk and must be run before dedup can be trusted corpus-wide. This is a small, offline task
(roadmap #29).

### Privacy is enforced in code

Ingested items default to `privacy: private`. The guard lives in **this repo's** conductor
client (`analysis/conductor.py`): any call routed to the paid T3 (cloud) tier **raises if it
carries a document marked private**. It cannot live in the conductor itself — that is a
sibling repo (`local-llm-conductor`) this project does not control, and a guarantee we cannot
enforce is not a guarantee. T1/T2 are local and unrestricted.

Public-tier material (a purchased ebook of a published book) is marked explicitly at review
time, by a human.

This preserves the project's posture: raw text stays local, and the value added is analysis,
structure, and access — never redistribution.

---

## Part 3 — Review CLI

`make ingest-review` → `python -m ingest.review`, mirroring `analysis/adjudicate.py`'s loop.

Per item, in order:

1. **Warnings first** — "PDF had no text layer, used OCR", "no date found", "OCR confidence 0.42".
2. Guessed metadata — title, date + confidence, modality, authorship.
3. First ~400 characters of extracted text.
4. A `file://` link to the original, so a scan or a video can be eyeballed directly.

Prompts: `[a]ccept / [e]dit / [r]eject / [s]kip / [q]uit`. `edit` walks only the fields worth
correcting: title, date, modality, authorship, privacy.

Two rules that decide whether this is actually *easy*:

- **Review is per source, not per document.** A book prompts once, not forty times. Confidence
  and warnings aggregate to worst-case across its documents.
- **Rejects are never deleted.** They move to `data/ingest/rejected/` with a reason, so a bad
  OCR pass is recoverable rather than destructive.

A non-interactive `--report` mode prints a queue summary (mirroring `adjudicate.print_report`).
It is safe for the nightly agent to run and paste into a PR, because it touches nothing.

---

## Testing

- **Every handler** gets a unit test against a **synthetic** fixture — a generated 2-page PDF,
  a 3-line `.eml`, a rendered PNG, a minimal epub. **No real family content ever enters git.**
- **Migration** is tested on a fixture manifest, including idempotency (running twice is a
  no-op) and the already-migrated case.
- **Review CLI** is tested by injecting a scripted input sequence, as `adjudicate` does.
- **Privacy guard** gets an explicit test: a `private` document routed at T3 must raise.
- `make verify` (ruff + pytest + dashboard smoke build) stays the gate.

## Roadmap items

Adds a new **`ingest`** category to the rotation in `docs/roadmap.md`. All items are offline,
pure, and unattended-safe.

| # | P·Size | Item |
|---|---|---|
| 29 | P1·S | `provenance` schema + pure migration of the 199 entries; run `backfill_hashes` |
| 30 | P1·S | Ingest skeleton: inbox, queue, `make ingest`, handler registry, `.txt`/`.md` |
| 31 | P1·S | Review CLI — interactive + `--report` |
| 32 | P2·S | `.eml`/`.mbox` handler (stdlib; thread split, quoted-reply strip) |
| 33 | P2·S | `.docx` handler |
| 34 | P2·M | `.pdf` handler + no-text-layer detection |
| 35 | P2·M | `.epub` handler + chapter segmentation — unlocks the books |
| 36 | P2·M | Image OCR handler |
| 37 | P3·L | Audio/video transcription (local Whisper) + timestamped segments |
| 38 | P2·S | Modality-aware analysis defaults + modality breakdown in the dashboard |

Items **29–31 are the thin end-to-end slice**, and they alone are the scope of the first
implementation plan: after them, a `.txt` file can go from `data/inbox/` to the corpus with
review. Items 32–38 are deliberately *not* in that plan — each is an independent night's work
for the nightly agent, added to `roadmap.md` under the new `ingest` category.

## Deferred

- **C3 — discovery agent.** An unattended sweep of public surfaces (Forbes index, X, university
  pages, podcasts, book listings) proposing candidates into the same review queue. Deferred
  until the queue exists. **X has no free API and active bot detection; the clean path is his
  X archive export, not scraping.** No detection evasion will be built.
- **C4 — family surface.** Includes the current **8 MB `dashboard/index.html`**, which inlines
  embeddings (3.7 MB), reading room (2.5 MB) and predictions (1 MB). This only worsens as the
  corpus grows, and should be solved against an already-enlarged corpus.

## Owner actions (not agent work)

- Request the **X archive export** (Settings → Download an archive) — the only clean route to
  the tweets.
- Purchase DRM-free ebooks for local extraction.
- Decide whether course materials can be obtained as originals; the design assumes they cannot
  and routes them through OCR/PDF like anything else.
