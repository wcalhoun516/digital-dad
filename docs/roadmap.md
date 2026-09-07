# Roadmap

**Source of truth** for what to build next. Human-curated. The daily product-dev agent reads
this to pick its cold-path work but **never edits it** — propose changes via a draft PR
comment or edit it yourself.

Legend: **P1** = do soon / high leverage · **P2** = valuable · **P3** = nice-to-have.
Size: **S** ≤ ~½ day · **M** ~1–2 days · **L** multi-day.
Categories (the agent rotates least-recently-worked first):
`infra · scraper · analysis · ingest · dashboard · training · family · docs`.

> Mark an item `(in progress: daily/<date>-<slug>)` or `(done <date>)` inline as it moves.

---

## 📋 Planned execution order (next ~2 weeks)

The daily agent runs pre-baked plans **oldest-first** before touching anything below, so this
queue is the deterministic, owner-chosen sequence. Each plan is sized to *deepen over 2–3 days*
(review cadence is a few times a week).

**Plans 0001–0008 are all complete** and live in `plans/done/`. The current queue is the
**Geo-LLM flywheel**: make the fine-tune work, widen what feeds it, then build the console that
turns the crank.

| Order | Plan | Roadmap items |
|-------|------|---------------|
| 1 | `plans/ready/0009-finetune-fair-test.md` | #39 → #40 (reshape training data, retrain, re-measure vs D15) |
| 2 | `plans/ready/0010-epub-ingest-handler.md` | #35 (books — the highest-yield corpus source) |
| 3 | `plans/ready/0011-operator-console.md` | #42 (upload → review → train → scoreboard) |

**Sequencing rationale** (design:
[`superpowers/specs/2026-09-07-next-phase-design.md`](superpowers/specs/2026-09-07-next-phase-design.md)):
0009 comes first because it is two nights and decisive — the QLoRA behind D15 trained on a
dataset where **138/138 records exceeded `max_seq_len`** and only ~33% of the corpus reached the
model. Until that is fixed, every new source ingested loses two-thirds of itself the same way.
Fix the lever, then feed it.

**After the queue drains**, prefer the remaining Geo-LLM arc (#41 modality-aware training, then
`.pdf` #34 / `.docx` #33), then the weekly-column arc (#43–#46). The one-night wins #47 and #48
can be dropped into any run.

**Note on the old family emphasis:** the previous version of this section said to prefer
#21/#23/#24 once the queue drained. All three shipped (2026-07/08) — the roadmap simply never
recorded it. The remaining family payoff is **reach and freshness** (#47, #48), not more
features.

---

## ✅ Already shipped (do not rebuild)

- **Ask Dad** — RAG chat over the corpus. `dashboard/template.html` + `analysis/semantic_search.py`.
- **Track Record** — falsifiable-prediction extraction + audit. `analysis/predictions.py` + dashboard tab.
- **On This Day** — weekly news→archive email in his voice. `analysis/on_this_day.py` + `bin/create_gmail_draft.py`.

---

## infra / ops — *do first; the agent needs these to verify its own work*

1. **P1 · S · infra** *(done)* — pytest + a `tests/` scaffold. Cover `analysis/utils` (`clean_text`,
   `chunk_text`), `scraper/utils` (`slugify`, `is_article_url`), and the corpus-fingerprint
   helper. → seeds `make test`. *(Pre-baked: `plans/ready/0001-verification-infrastructure.md`.)*
2. **P1 · S · infra** *(done)* — ruff lint+format config in `pyproject.toml` + `make lint` / `make fmt`.
3. **P1 · S · infra** *(done)* — `make verify` = lint + tests + dashboard smoke build. This is the
   command the daily agent's §7 fast-verification should prefer once it exists.
4. **P2 · M · infra** *(done)* — GitHub Actions CI running `make verify` on every PR. *(queued: ready/0002)*
5. **P3 · S · infra** *(done)* — pre-commit hooks (ruff + JSON validity check on `data/analysis/*.json`).
6. **P2 · M · ops** *(done)* — conductor preflight as a reusable Python helper (one health check,
   clear error message) shared by every module instead of ad-hoc curl in `weekly_run.sh`.
7. **P3 · M · ops** *(done)* — structured logging across analysis modules (replace `print`) + `--verbose`.

## scraper

8. **P2 · S · scraper** *(done)* — manifest integrity checker: detect orphaned `data/raw/*.json`,
   missing/duplicate `content_hash`, manifest/disk drift. Surface as a `make` target.
9. **P2 · M · scraper** *(done)* — coverage audit vs the Forbes author index: report missing date
   ranges / slugs so we know what the archive is still missing.
10. **P3 · M · scraper** *(done)* — richer metadata per article: canonical URL, original-vs-updated
    date, section, byline variants.

## ingest

**Corpus II** — a reviewed, offline second front door for material beyond Forbes: books,
course materials, letters, email, messages, talks. Design:
[`superpowers/specs/2026-08-13-corpus-ingest-design.md`](superpowers/specs/2026-08-13-corpus-ingest-design.md).

Every item is offline, pure, and unattended-safe. A handler is a pure
`(Path) -> ExtractResult` registered by extension, so each new format is an isolated PR.

29. **P1 · S · ingest** — `provenance` schema + pure migration of the manifest;
    backfill `content_hash`. *(done 2026-08-16; the one-time data migration is still
    pending — see the deviation note in the plan)*
30. **P1 · S · ingest** — ingest skeleton: inbox, queue, `make ingest`, handler registry,
    `.txt`/`.md` handler. *(done 2026-08-16)*
31. **P1 · S · ingest** — review CLI, interactive + `--report`. *(done 2026-08-16)*
32. **P2 · S · ingest** *(done)* — `.eml`/`.mbox` handler (stdlib `email`/`mailbox`; thread split,
    quoted-reply stripping, one document per message).
33. **P2 · S · ingest** — `.docx` handler (first user of the new opt-in `ingest` extra).
    *Sequenced after #35 and #34.*
34. **P2 · M · ingest** — `.pdf` handler + no-text-layer detection (warn and defer to OCR).
    *Sequenced after #35.*
35. **P1 · M · ingest** — `.epub` handler + chapter segmentation. **Unlocks the books —
    ~80k words ≈ the entire current corpus, so one ebook roughly doubles the training set.**
    Promoted to P1 and moved to the front of the ingest arc. Stdlib (`zipfile` + `html.parser`),
    no new dependency. *(queued: ready/0010)*
36. **P2 · M · ingest** — image OCR handler with a confidence score.
37. **P3 · L · ingest** — audio/video transcription (local Whisper) + timestamped segments.
    **Parked** — no source material in hand, and spoken register is not written register: see
    #41 before mixing transcripts into any voice fine-tune.
38. **P2 · S · analysis** — modality-aware analysis defaults (`authorship: george`) and a
    modality breakdown in the dashboard. Also lands the T3 private-document guard in
    `analysis/conductor.py` and writes `data/raw/<id>.json` for ingested items.

## analysis

11. **P1 · L · analysis** *(done)* — prediction-verdict **backfill**: a web-search-augmented T3 pass to
    propose verdicts, plus a tiny JSON-edit adjudication CLI so the family can confirm/override.
    This is the "slow part" that makes Track Record fully alive. *(queued: ready/0004)*
12. **P2 · M · analysis** *(done)* — confidence calibration for Track Record: hit-rate by confidence
    language (hedged/confident/certain), Brier-style scoring, "most right / most wrong" boards. *(queued: ready/0004 deepen)*
13. **P2 · M · analysis** *(done)* — "intellectual arc": theme evolution year-over-year with a
    generated narrative of how his focus shifted.
14. **P2 · L · analysis** *(done)* — entity co-occurrence graph (people/orgs) feeding a new dashboard
    network viz. Builds on `entities.py`.
15. **P3 · M · analysis** *(done)* — contradiction / mind-change finder: where did he revise a view?
16. **P3 · S · analysis** *(done)* — "Calhoun-isms": most quotable/aphoristic sentences per theme.
17. **P2 · M · analysis** *(done)* — per-entity stance over time (e.g. his evolving view of the Fed,
    Bitcoin, the ECB).

## dashboard / family-facing

18. **P2 · S · dashboard** *(done)* — "Ask Dad" chat persistence (localStorage) + transcript export. *(queued: ready/0005)*
19. **P2 · M · dashboard** *(done)* — Ask Dad citations deep-link into the Raw Corpus tab and highlight
    the matched passage. *(queued: ready/0005 deepen)*
20. **P2 · M · dashboard** *(done)* — mobile-responsive pass (the family will open this on phones). *(queued: ready/0006)*
21. **P3 · M · dashboard** *(done)* — "Reading room": clean, paginated full-article reader with
    prev/next and theme tags.

## family

22. **P1 · M · family** *(done)* — On This Day **auto-send** (beyond draft): configurable recipient
    list + a pre-send editorial override step. Builds on `on_this_day.py` + D9. *(queued: ready/0003)*
23. **P3 · M · family** *(done)* — annual "year in review" digest email (best predictions, top themes).
24. **P3 · M · family** *(done)* — printable/PDF "best of" anthology generator.

## training / ML

25. **P1 · M · training** *(done)* — RAG faithfulness eval harness: held-out articles, measure Ask Dad
    citation accuracy and hallucination rate. Establishes the baseline before any fine-tune. *(queued: ready/0007)*
26. **~~P2 · L · training~~ — "Geo LLM" (original fine-tune ladder) — *RETIRED, superseded by #39–#42.***
    D15 recorded the verdict; plan 0008 is in `plans/done/`. The ladder is replaced by the
    reshaped-dataset re-test (#39/#40) — see plan 0009. Original text kept below for history.
    **Geo LLM: fine-tune a George-Calhoun-voice model.** The big one,
    broken into bite-size, individually-shippable experiments so it fits the daily cadence.
    Each lands as its own small PR; the ladder is sequenced in `plans/ready/0008-geo-llm-finetune.md`.
    Builds on the existing `notebooks/finetune_qlora.ipynb` + `training/prepare.py`, and is
    measured against the #25 RAG baseline. *(queued: ready/0008)*
    - **26a · S** — Dataset builder: corpus → instruction/chat pairs in his voice + a held-out
      split (extends `training/prepare.py`; writes `data/training/{train,heldout}.jsonl`).
    - **26b · S** — Capture the pre-fine-tune **baseline** numbers (RAG voice + factuality from
      #25) as the bar any fine-tune must beat. One JSON + a short writeup.
    - **26c · M** — Smallest viable QLoRA run on a small local base (e.g. Qwen2.5-3B / Llama-3.2-3B)
      via the existing notebook → produce an adapter + a handful of smoke generations. The "is
      this even tractable on the M4?" experiment.
    - **26d · M** — Voice-fidelity eval harness: blind A/B (RAG vs fine-tuned vs real excerpts)
      scored by a judge model through the conductor (T3), plus simple style metrics. Reusable.
    - **26e · S** — Register the adapter/merged model in the conductor (`models.yaml`) as a
      tier/function so Ask Dad can *optionally* answer via the fine-tune behind a flag.
    - **26f · S** — Compare & decide: fine-tune vs RAG on faithfulness + voice; record the call
      (and cost) in `docs/decisions.md`.
27. **P3 · M · training** *(done)* — embedding-model comparison before ever changing the pinned model (D2).

## docs

28. **P3 · S · docs** *(done)* — "how to add a new analysis module" runbook + a formal written
    conductor-contract doc (chat/embeddings signatures, tiers, error modes).

---

# 🆕 Next phase — the Geo-LLM flywheel (2026-09-07)

Added after the 2026-09-07 planning session. Design:
[`superpowers/specs/2026-09-07-next-phase-design.md`](superpowers/specs/2026-09-07-next-phase-design.md).

**Why this phase exists.** #1–#32 are shipped; the roadmap above is drained except the ingest
arc. The stated goal of the project is the **Geo-LLM** — a model that writes in his voice,
grounded in his real work — and the flywheel that feeds it: get material in, shape it into
training data, train, evaluate, repeat.

**The finding that set the order.** The QLoRA behind D15 was never given a fair test.
`training/prepare.py` emits one record per article (median ~2,952 est. tokens) against
`max_seq_len = 1024`, so **138/138 training records were truncated** and only ~33% of the corpus
reached the model — all of it article *openings*. `make finetune-preflight` has been reporting
this as **FAIL** the whole time, but it exits 0 by design, so nothing blocked on it. D15's
verdict stands until re-measured; its stated revival path (more examples, more iters, higher
rank) is superseded — the defect is example **shape**, not count.

## training / ML

39. **P1 · S · training** — passage-level training records. Chunk article bodies on paragraph
    boundaries into complete records that fit `max_seq_len`, with varied task shapes; keep the
    held-out split **article-level** so chunks cannot leak across it. ~800–1,200 examples from
    the 204 articles already in hand, using 100% of the corpus instead of 33%. No new source
    material, no new dependency. *(queued: ready/0009)*
40. **P1 · S · training** — retrain on the reshaped set and re-measure against D15's baseline
    (fine-tune 0% win-rate / avg rank 2.88; RAG 1.50; real 1.63; TTR 0.35 vs 0.70). Record the
    result as an ADR **including a negative one** — a fair test that still loses is a real
    finding. Owner-interactive (local GPU hours + a paid T3 judge). *(queued: ready/0009)*
41. **P1 · M · training** — modality-aware training + per-modality voice eval. Filter/condition
    on `provenance.modality` and `authorship: george`, and slice `voice_eval` by modality.
    Spoken register is not written register: talk transcripts mixed unlabelled into a
    written-voice fine-tune can *lower* fidelity measured against columns. Needed before #37.

## infra

42. **P1 · L · infra** — operator console on `bin/serve_dashboard.py`: upload → review queue →
    trigger rebuild/train/eval as a background job → **eval scoreboard** showing run-over-run
    deltas against D15's standing numbers. Stdlib only, no framework. **Must be served
    tailnet-only, not on the public Funnel** — it adds file upload and job execution to a
    surface that is currently read-only and internet-reachable behind one shared password.
    Needs its own ADR for the console-vs-D4 split. *(queued: ready/0011)*

## analysis / family — the weekly column

The weekly commentary the owner actually wants: current events, in his voice, every claim
citable, closing with his adjudicated record on the subject. Today `on_this_day.py` cosine-
matches a headline to one article and wraps it in 2–3 generated sentences — a retrieval match,
not a commentary. The missing unit is **positions**: the archive can retrieve articles and
passages, but not what he *held to be true*.

43. **P2 · M · analysis** — positions index (`data/analysis/positions.json`). Group the 611
    adjudicated claims from 404 free-text topic strings into subjects, each with its claims,
    date span and won/lost record via `adjudicate.effective_verdict`. Reusable by Ask Dad and
    year-in-review, not just the column.
44. **P2 · M · analysis** — subject selection from strength: score this week's headlines against
    the positions index (match × depth × adjudicated coverage × recency) and emit a numbered
    evidence pack. **Must be able to return "nothing this week"** rather than manufacture a
    column.
45. **P2 · L · family** — the weekly column: one voice, inline citations, RAG-grounded (not the
    fine-tune, until #40 says otherwise), closing with his record on the subject.
46. **P2 · M · analysis** — citation verifier / publish gate. Pure and offline; **fails closed**.
    Every `[n]` resolves to a real source; every quoted span appears verbatim in the article it
    cites; every paragraph carries a marker. An unverified column is never rendered or drafted.

## one-night wins — droppable into any run

47. **P2 · S · infra** — put the derived builders into the weekly refresh. `make analyze` runs
    6 of 12 builders, so `reading_room`, `entity_graph`, `intellectual_arc`, `calhoun_isms`,
    `contradictions` and `entity_stance` sit 3–7 weeks stale while the tabs beside them refresh
    weekly. Directly redeems the "living archive, not a museum" claim.
48. **P2 · S · family** — delivery for the keepsakes. `delivery.latest_email_payload()` globs
    only `on_this_day_*.html`, so year-in-review and anthology can be rendered and never sent.
    Generalize the glob; add `make send-year-in-review`.

## retired / downgraded (2026-09-07)

- **#26 + plan 0008 — RETIRED.** D15 settled it; superseded by #39–#42. Plan is in `plans/done/`.
- **#17 `entity_stance` — downgrade to P3.** It computes mean sentiment polarity per entity per
  year (`Federal Reserve: -0.0337, trend steady`). That is a mood ring, not a position, and no
  surface uses it meaningfully. Fold its trajectory data into #43 or drop the tab.
- **#37 audio/video — parked.** No source material in hand; blocked on #41 regardless.
- **#5, #7, #9, #10 — done, and no successors planned.** The corpus produced 6 articles in 2026
  and is thinning; scraper and ops polish has hit diminishing returns.
