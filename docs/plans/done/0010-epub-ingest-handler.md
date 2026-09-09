# Plan 0010 — `.epub` ingest handler: unlock the books

## Goal

Add an `.epub` handler to the ingest registry, with chapter segmentation, so a DRM-free ebook
of Dr. Calhoun's own work enters the corpus as one source yielding many documents.

Roadmap **#35**, promoted to **P1** and moved to the front of the ingest arc. Design:
[`superpowers/specs/2026-08-13-corpus-ingest-design.md`](../../superpowers/specs/2026-08-13-corpus-ingest-design.md)
and [`2026-09-07-next-phase-design.md`](../../superpowers/specs/2026-09-07-next-phase-design.md).

## Context — why this handler before the others

A book is roughly **80,000 words ≈ the entire current 204-article corpus**. One ebook
approximately doubles the material available to the Geo-LLM training set. Nothing else in the
ingest arc (`.pdf`, `.docx`, OCR, audio) comes close on yield per unit of effort, which is why
this moves ahead of #33/#34.

**Sequencing note:** plan 0009 reshapes the training-data builder so records fit the fine-tune
window. Until that lands, ~67% of any ingested book is discarded at training time exactly as
the articles were. This plan is still worth doing in parallel — the corpus is valuable to Ask
Dad, the reading room and the column regardless — but the *training* payoff arrives only once
0009 has shipped. Do not claim a training win in this PR.

### The handler contract already exists

```python
@register(".epub")
def extract_epub(path: Path) -> ExtractResult: ...
```

`ExtractResult(documents, meta, confidence, warnings)`; each document is
`{"title": str, "text": str, "ordinal": int}`; `empty_meta(title)` seeds provenance defaults
(`modality: letter`, `authorship: george`, `privacy: private`) which the **review CLI** is where
a human corrects — not the handler. Follow `ingest/handlers/mail.py` (merged 2026-09-05, PR #87)
as the reference implementation; register the module in `ingest/handlers/__init__.py`, which is
what activates a format.

### Dependency decision — stdlib, not a library

The 2026-08-13 design assigned `.epub` to the opt-in `ingest` extra. **Recommend stdlib
instead.** An EPUB is a ZIP containing XHTML:

```
META-INF/container.xml  →  the .opf package path
<package>/content.opf   →  <manifest> (id → href) + <spine> (reading order)
                        →  XHTML documents, one per chapter
```

`zipfile` + `xml.etree.ElementTree` + `html.parser` cover all of it, which keeps the
zero-dependency core intact, keeps the handler pure and unattended-safe, and keeps CI able to
run its tests with no extra install — the same call that made `.eml` stdlib. Create the
`ingest` extra when `.pdf`/`.docx` genuinely need it (plan 0011+), not speculatively here.

If a real ebook defeats stdlib parsing in practice, that is a finding worth recording in the
PR — do not silently add a dependency to route around it.

## Steps — each step is its own PR-sized slice

Use `superpowers:test-driven-development`. Everything here is pure, offline and
unattended-safe.

1. **Container + spine parsing (S).** Pure functions: read `META-INF/container.xml` → locate the
   `.opf` → parse `<manifest>` and `<spine>` → produce the **ordered** list of XHTML hrefs.
   Reading order comes from the spine, never from ZIP entry order or filename sorting. Handle
   the namespace-prefixed and unprefixed forms both — real EPUBs vary.
2. **XHTML → text (S).** An `html.parser` subclass that strips markup, drops `<script>`/
   `<style>`, preserves paragraph breaks, and collapses whitespace. Chapter title from the first
   `<h1>`/`<h2>`, falling back to the spine item id. Reuse `analysis.utils.clean_text` for the
   final normalization rather than writing a second cleaner.
3. **Chapter segmentation → documents (S).** One document per spine item, `ordinal` = spine
   position. **Drop front/back matter** — copyright pages, dedications, indexes, "about the
   author" — by a conservative heuristic (very short items, plus a title allow/deny list),
   because that material is not his prose and will pollute a voice fine-tune. Every drop is a
   `warning`, never a silent removal.
4. **Metadata + confidence (S).** Title/author/date from the OPF `<metadata>` Dublin Core
   fields. Confidence reflects what was actually recovered (missing title or unparseable spine
   lowers it). **Warn loudly when the OPF author is not Calhoun** — an ebook of someone else's
   book must not enter as `authorship: george`; the review CLI is the gate, and the warning is
   what makes a reviewer look.
5. **DRM detection (S).** An encrypted EPUB (`META-INF/encryption.xml`, or unreadable
   XHTML) must fail with a clear "this file is DRM-protected — a DRM-free copy is required"
   warning at zero confidence. It must never enter the queue as garbage text. **No DRM
   circumvention of any kind** — detect and refuse.
6. **Docs (S).** `ingest/README.md` section + the format table in the architecture doc.

## Verification

- **Synthetic fixtures only** — build a minimal valid EPUB in the test (a `zipfile` written to
  `tmp_path` with a container, an OPF and two XHTML chapters). **No real book, and no family
  content, ever enters git**, per the ingest design's testing rule and D7.
- Tests to prove red first: spine ordering (including a deliberately shuffled ZIP), namespace
  variants, entity unescaping, front-matter dropping with its warning, a non-Calhoun author
  warning, an encrypted EPUB refused at zero confidence, a malformed/absent OPF handled without
  raising.
- The handler must be **pure**: no network, input file unmutated, deterministic output for a
  given file. A test that runs it twice and compares.
- `make verify` green; paste real output per §7.
- **Owner-run, not agent-run:** actually ingesting a real book (`make ingest` →
  `make ingest-review`) needs a purchased DRM-free file the agent does not have. Leave that to
  the owner and say so in the PR.
- Clear `__pycache__` before trusting any red→green proof (external-volume stale `.pyc`).
- `superpowers:verification-before-completion` before flipping to ready.

## Out of scope

- **Any DRM circumvention.** Detect, warn, refuse. The owner buys DRM-free copies; that is
  recorded as an owner action in the corpus-ingest design.
- `.pdf`, `.docx`, OCR, audio — later slices of the ingest arc.
- Changing analysis modules. The design's load-bearing decision holds: one source yields many
  documents, and every downstream module keeps operating on documents unchanged.
- Committing any ingested text. `data/inbox/`, `data/ingest/` and `data/raw/` stay gitignored.
- Modality-aware training weights — that is roadmap #41, and it needs 0009 first.
