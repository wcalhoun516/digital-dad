# Design — Next phase: the Geo-LLM flywheel and the weekly column

**Date:** 2026-09-07
**Status:** approved (design), pending implementation plans
**Touches:** `training/prepare.py`, `training/finetune_config.py`, new `analysis/positions.py`,
`analysis/weekly_column.py`, `analysis/citations.py`, `bin/serve_dashboard.py`, `ingest/handlers/`,
`Makefile`. New artifacts: `data/analysis/positions.json`, `data/cron/columns/`.

## Goal

Two arcs, designed together because the second is where the first ships.

- **A — Geo-LLM flywheel.** Make the fine-tuned voice model *improvable*: properly-shaped
  training data, a widening corpus, and a console that turns the crank and keeps score.
- **B — The weekly column.** A weekly commentary on current events, written in his voice,
  where every claim is citable to a real article and the piece states his adjudicated record
  on the subject. Not a matched archive article with an intro pasted on top.

The owner's stated north star is Arc A. Arc B is the product surface Arc A eventually plugs
into (roadmap 26e was already "let Ask Dad answer via the fine-tune behind a flag"), and it
doubles as a recurring, real-world test of whether the model writes like him.

---

## Finding — the fine-tune was never given a fair test

This is the load-bearing discovery of this design, and it reverses D15's prescription.

`training/prepare.py::build_instruct_record` emits **one record per article**: prompt
`"Write an analysis of <title>"`, completion = the entire article body.
`training/finetune_config.py::QLoRAConfig.max_seq_len` is **1024 tokens**.

Measured on the shipped `data/training/train.jsonl`:

| | |
|---|---|
| train records | 138 |
| assistant completion, median | ~11,811 chars ≈ **2,952 tokens** |
| records exceeding `max_seq_len` | **138 / 138 (100%)** |
| training signal retained | ~141,312 of ~416,304 tokens (**33%**) |

Every example was truncated. The model trained on roughly 141k tokens — about one third of a
single book — and all of it was article **openings**: epigraph quotes, datelines, thesis
paragraphs. It never saw a conclusion, a sustained argument, or a section transition.

D15's own style metrics are the fingerprint of exactly this: type-token ratio 0.35 against a
real-corpus 0.70 (openings are formulaic *across* articles), and ~2× over-use of his
distinctive hinge vocabulary ("Notably", "Crucially") — words that concentrate in openings.
D15 read this as "it learned surface markers, not fluency." The observation is right; the
cause is not that 138 examples were too few to generalize from, but that the surface was the
only thing the model was ever shown.

**Consequence for D15.** D15 prescribed *more examples-per-article (138 → 500+), more iters,
higher LoRA rank*. Example count is a symptom. The disease is **shape**: one oversized example
per article against a 1024-token window. D15's verdict (RAG is the product voice) should stand
until re-measured, but its stated revival path should be superseded by this design. A new ADR
records the correction; D15 is not deleted.

**Consequence for ingestion.** Widening the corpus multiplies a lever that currently discards
two-thirds of its input. A book ingested today loses 67% of itself the same way. Reshaping the
dataset builder first makes every future source worth 3–4× more. This is the argument *for*
the ingest arc, correctly sequenced — not against it.

---

## Arc A — the flywheel

### A1. Reshape the training data (the decisive experiment)

Chunk articles into passage-level examples that fit the window. 204 articles ÷ ~3k tokens ÷
1024 ≈ 3–4 complete chunks each → **800–1,200 well-formed examples** from the existing corpus,
using 100% of it instead of 33%. No new source material, no new dependencies.

Design notes:

- Chunk on **paragraph boundaries**, never mid-sentence. Reuse `analysis/utils.chunk_text`
  rather than inventing a second chunker.
- Vary the **task shape** so the model learns more than one move: continue-this-passage,
  write-on-this-topic, respond-to-this-claim. One shape per record; shapes are recorded in the
  record so evals can slice by them.
- Keep the held-out split **article-level**, not chunk-level — chunks from one article must
  never straddle train/heldout, or the eval leaks. This is a real trap: the current split is
  slug-keyed and safe, and chunking is exactly what would break it.
- `max_seq_len` stays 1024. The fix is data shape, not a bigger window; a bigger window on a
  16GB M4 trades against batch size and rank.

Then retrain and re-run `make voice-eval` against D15's recorded numbers. **This is cheap and
decisive.** If properly-shaped data does not move the eval, that is learned before six file
handlers are built to feed it.

### A2. Ingest for volume — books first

Existing arc (#33–#37), reordered by yield per unit of effort:

1. **`.epub` (#35)** — a book is ~80k words ≈ the entire current corpus. One DRM-free ebook
   roughly doubles the training set. Highest-value handler by a wide margin.
2. **`.pdf` (#34)** — course materials, papers, scanned pieces.
3. **`.docx` (#33)** — drafts and manuscripts.
4. **OCR (#36)**, then **audio/video (#37)**.

**Modality is not cosmetic here.** Spoken register is not written register: talks and
interviews have different sentence length, no em-dashes, no epigraphs. Mixed unlabelled into a
written-voice fine-tune, transcripts can *lower* voice fidelity measured against a corpus of
columns. The provenance model already carries `modality` (see the 2026-08-13 corpus-ingest
design), so:

- the dataset builder filters or conditions on `modality` and `authorship: george`;
- `voice_eval` gains a per-modality slice so the effect is measured rather than assumed.

This is also an argument for books before video, independent of yield.

### A3. The operator console

**Host:** `bin/serve_dashboard.py` — 199 lines of stdlib `ThreadingHTTPServer` with HTTP Basic
Auth, already running under `com.calhoun.digitaldad-dashboard`, already funnelled at `:8443`,
and already carrying a `do_POST` path. The console is a new authenticated surface on that
server. No framework, no build step, no new dependency.

**Relationship to D4.** D4 makes the *family dashboard* fully client-side for durability — a
single `index.html` that opens anywhere, forever. The console has the opposite requirements: it
must write files and start jobs, so it is inherently server-bound. These are two different
surfaces with two different jobs, and the console must not be allowed to creep into the
family artifact. A new ADR records this rather than leaving it as a silent exception to D4.

**Four jobs:**

1. **Drop files** → writes into `data/inbox/`, the ingest front door that already exists.
2. **Review queue** → the web equivalent of `make ingest-review`: warnings, guessed metadata,
   first ~400 chars, accept / edit / reject, **per source, not per document**.
3. **Turn the crank** → rebuild training data → train → eval, as a **background job** with
   streamed logs. Never in the request handler.
4. **Scoreboard** → `voice_eval` and `rag_eval` results across runs, so run N can be compared
   to run N−1.

The scoreboard is the point. Geo-LLM stalled because it was a one-shot experiment that failed
once and was shelved by an ADR; nobody could see whether a change helped. A flywheel needs a
dial.

**Safety constraints:**

- Training is long and resource-hungry: an explicit, owner-only trigger with a visible
  running-job state. One job at a time; a second request is refused, not queued silently.
- Uploads are bounded by size and extension, written under `data/inbox/` only, never executed.
- The auth gate already exists and refuses to start without a password — the console must
  inherit it, and must never be reachable on the open Funnel unauthenticated.
- Ingested material defaults to `privacy: private`, and the existing T3 guard in
  `analysis/conductor.py` keeps private documents off the paid cloud tier.

---

## Arc B — the weekly column

### The gap

`analysis/on_this_day.py` embeds RSS headlines, cosine-matches each to one archive article,
and asks the local model for 2–3 sentences on why it is relevant — ending literally with
`"See the full piece below."` and pasting the article. The generated content is about three
sentences of connective tissue; the intelligence is a similarity match, not a commentary.

The archive can retrieve **articles** (On This Day) and **passages** (Ask Dad). Nothing
retrieves **positions** — what he held to be true, when, and whether it panned out.

### The material that already exists

`data/analysis/predictions.json`: **611 dated, sourced, falsifiable claims**, of which 549 are
adjudicated (151 vindicated · 205 mixed · 124 wrong · 69 unfalsifiable), each with topic,
confidence language, and source article. Spread across **404 free-text topic strings** — the
doctrine is present and scored, but not grouped.

### Components

**`analysis/positions.py` → `data/analysis/positions.json`.** Groups the 611 claims into
subjects. Grouping is embedding clustering over topic + claim text using the pinned
`sbert-mpnet-v2` (D2), with `entity_aliases.canonicalize()` doing cheap normalization first.
`build_positions(predictions, *, embed, threshold)` takes `embed` as an injected seam so
clustering is testable offline against a fake embedder. One record per subject:

```json
{ "id": "pos:federal-reserve-policy",
  "subject": "Federal Reserve policy",
  "aliases": ["Fed policy", "Fed rate decisions", "FOMC"],
  "claims": [ {"claim": "...", "date": "2023-03-11", "slug": "...", "url": "...",
               "confidence_language": "confident", "verdict": "vindicated"} ],
  "span": ["2020-04-13", "2025-11-02"],
  "record": {"vindicated": 2, "mixed": 1, "wrong": 1, "unfalsifiable": 0, "pending": 0} }
```

Verdicts resolve through `adjudicate.effective_verdict`, so a human ruling from `make
adjudicate` outranks the advisory LLM one for free.

**`analysis/weekly_column.py`.** Mirrors `rag_eval.py`'s structure — pure helpers plus a
harness with injected seams:

- `score_subjects(headlines, positions, *, embed)` — match this week's headlines against
  subjects; score on match strength × archive depth × adjudicated coverage × recency.
- `select_subject(...) -> TopicMatch | None` — **`None` is a first-class outcome.** If he has
  no real doctrine on this week's news, no column runs. The corpus picks the subject, not the
  news cycle. Forcing a column weekly is how it starts hallucinating.
- `build_evidence_pack(match, *, retrieve)` — his claims plus supporting passages from
  `semantic_search`, numbered `[1..n]`, each bound to slug + title + url.
- `compose(pack, *, generate)` — the in-voice column with `[n]` markers. Live wiring is the
  conductor at T2. **RAG-grounded, not the fine-tune** — until the A1 re-measurement says
  otherwise, D15 stands and the shipped voice is retrieval.
- `render_html(column, pack, record)` — email HTML including the record block.

**`analysis/citations.py` — the publish gate.** Pure, offline, stdlib. Fails closed.

| Hard failure (blocks publication) | Catches |
|---|---|
| Every `[n]` resolves to a source in the pack | Fabricated citations |
| Every quoted span appears verbatim in the article it cites | Words put in his mouth |
| At least one marker in the column | Ungrounded essay |
| Every paragraph carries ≥1 marker | Grounded opening, invented remainder |

Warnings (published but recorded): a sentence with a figure but no marker; unused sources;
any date asserted beyond the corpus span.

Quote matching normalizes whitespace, case, and curly-vs-straight quotes and dashes **for
comparison only** — rendered text keeps what was written, since the em-dashes are half the
voice.

**The honest limit.** Verbatim checking binds only text placed inside quotation marks.
Paraphrase carries a marker but gets no mechanical check. The gate therefore catches the two
failure modes that would genuinely embarrass the family — invented quotations and invented
sources — and does not catch subtle misrepresentation of a position. For that, `rag_eval.py`
already has a T3 entailment judge with a `parse_judgment` parser; it is wired as an **opt-in
second gate** (`--judge`), off by default because it is paid. Free mechanical gate always;
paid semantic gate on request.

### Data flow

```
RSS headlines ──┐
                ├─► score_subjects ─► select_subject ─► build_evidence_pack ─► compose ─► verify ─┬─ ok ──► render ─► data/cron/columns/*.html ─► Gmail draft (D9)
positions.json ─┘      (embed)        may be None          (retrieve)        (generate)          └─ fail ─► retry ≤2 ─► abort + report; nothing rendered
```

Reused wholesale: `on_this_day._fetch_headlines`, `semantic_search` retrieval and `_embed_one`,
`adjudicate.effective_verdict`, `analysis/delivery.py` for the draft,
`entity_aliases.canonicalize`. Nothing here duplicates an existing abstraction.

`on_this_day.py` is untouched and keeps running. Retiring it is a decision for after the column
has proven itself, not a precondition.

### Failure modes — three outcomes, deliberately different in loudness

1. **No subject clears the bar** → no column, exit 0, one log line. Quiet and normal. Some
   weeks he has nothing to say about the news, and the archive should be willing to say so.
2. **Composed but failed verification** → retry composition ≤2 times with the specific errors
   fed back; if still failing, write `data/cron/columns/failed_<date>.json` with the errors and
   the rejected draft, exit non-zero. Loud in the cron log. **Nothing rendered, nothing
   drafted.**
3. **Verified** → render, write `weekly_column_<date>.{html,json}`, hand to the Gmail draft
   path per D9.

Failure mode 2 must not degrade to "send it anyway with a disclaimer." This is the artifact the
owner has been unwilling to send for months; a gate that can be talked out of failing is not a
gate.

---

## Testing

Following the established repo shape — pure functions TDD'd offline, seams injected, CLI gated
on the conductor.

- **`prepare.py` (A1)** — chunk boundaries never split sentences; the article-level split holds
  under chunking (no article's chunks straddle train/heldout); a record count assertion that
  would fail if the builder regressed to one-record-per-article; a guard that no emitted record
  exceeds `max_seq_len`.
- **`positions.py`** — clustering against a fake `embed` with fixed vectors, so cluster
  boundaries are asserted exactly. Alias folding (`Fed policy` / `FOMC` → one subject). Record
  tallies computed through `effective_verdict`, pinned by a test so a human ruling wins.
- **`weekly_column.py`** — `score_subjects` ranking, and specifically that `select_subject`
  **returns `None`** on a thin week. That test is the difference between an archive with
  standards and a weekly hallucination.
- **`citations.py`** — each hard failure proved red against a hand-built bad column: a `[7]`
  with five sources, a quote with one word changed, an unmarked paragraph. Plus normalization
  cases (curly quotes, em-dashes, collapsed whitespace).
- **Console** — pure request-routing and upload-validation logic tested offline; no test starts
  a training job.
- **Real-corpus guards** — as in `test_year_in_review.py`: run against shipped artifacts (skip
  if absent), asserting invariants rather than frozen numbers, so re-adjudication does not make
  them brittle.
- No fixture contains real family content; synthetic articles throughout.

**Repo-specific trap:** this repo lives on an external volume and `pytest` has served a stale
`__pycache__` `.pyc` after an in-place rewrite. Clear it before trusting any red→green proof.

---

## Sequencing

| Phase | Work | Why here |
|---|---|---|
| **0** | Reshape training data, retrain, re-measure vs D15 | Cheap and decisive; de-risks everything downstream |
| **1** | Ingest for volume: `.epub` → `.pdf` → `.docx` | Now each source yields 3–4× more usable signal |
| **2** | Operator console: upload, review, train, scoreboard | Turns the crank without a terminal |
| **3** | Weekly column: positions → selection → compose → gate | The surface the model ships into |

Interleaved small wins, each one night, independent of the above:

- Put the six derived builders into the weekly refresh (`make analyze` runs 6 of 12;
  reading_room, entity_graph, intellectual_arc, calhoun_isms, contradictions and entity_stance
  are 3–7 weeks stale while the tabs beside them refresh weekly).
- Generalize `delivery.latest_email_payload()` beyond `on_this_day_*.html` so year-in-review
  and anthology can actually be sent.

## Out of scope

- Changing the pinned embedding model (D2) — that is roadmap #27 and invalidates the index.
- Auto-send without a human gate — D9 stands.
- Making the family dashboard server-dependent — D4 stands; the console is a separate surface.
- Enabling the fine-tune in any family-facing output before A1's re-measurement beats RAG.

## Owner actions (not agent work)

- Move `docs/plans/ready/0008-geo-llm-finetune.md` to `docs/plans/done/` — D15 settled it, and
  it has been picked up and discarded by the nightly agent every run since 2026-06-24.
- Mark shipped items done in `docs/roadmap.md` (#13, #14, #15, #16, #17, #21, #23, #24, #27,
  #28, #29–#32) — the roadmap is read-only to the agent by D12.
- Obtain DRM-free ebooks of his books for local extraction.
- Gather talk/lecture/interview recordings, if the audio arc is wanted later.
