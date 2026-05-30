# Roadmap

**Source of truth** for what to build next. Human-curated. The daily product-dev agent reads
this to pick its cold-path work but **never edits it** — propose changes via a draft PR
comment or edit it yourself.

Legend: **P1** = do soon / high leverage · **P2** = valuable · **P3** = nice-to-have.
Size: **S** ≤ ~½ day · **M** ~1–2 days · **L** multi-day.
Categories (the agent rotates least-recently-worked first):
`infra · scraper · analysis · dashboard · training · family · docs`.

> Mark an item `(in progress: daily/<date>-<slug>)` or `(done <date>)` inline as it moves.

---

## 📋 Planned execution order (next ~2 weeks)

The daily agent runs pre-baked plans **oldest-first** before touching anything below, so this
queue is the deterministic, owner-chosen sequence. Foundation first, then the four
must-haves, ordered for family/emotional payoff. Each plan is sized to *deepen over 2–3 days*
(review cadence is a few times a week).

| Order | Plan | Roadmap items |
|-------|------|---------------|
| 1 | `plans/ready/0001-verification-infrastructure.md` | #1–3 (tests, ruff, `make verify`) |
| 2 | `plans/ready/0002-ci-github-actions.md` | #4 (CI on PRs) |
| 3 | `plans/ready/0003-on-this-day-autosend.md` | #22 (email reaches the family) |
| 4 | `plans/ready/0004-track-record-alive.md` | #11 → #12 (verdict backfill + calibration) |
| 5 | `plans/ready/0005-ask-dad-polish.md` | #18 → #19 (persistence + citation deep-links) |
| 6 | `plans/ready/0006-mobile-responsive-dashboard.md` | #20 (phones) |
| 7 | `plans/ready/0007-rag-faithfulness-eval.md` | #25 (trust / voice baseline) |

**After the queue drains**, the cold path resumes with an **emotional / family-payoff**
emphasis — prefer family items (reading room #21, year-in-review #23, anthology #24) before
the analytical-depth and ops items.

---

## ✅ Already shipped (do not rebuild)

- **Ask Dad** — RAG chat over the corpus. `dashboard/template.html` + `analysis/semantic_search.py`.
- **Track Record** — falsifiable-prediction extraction + audit. `analysis/predictions.py` + dashboard tab.
- **On This Day** — weekly news→archive email in his voice. `analysis/on_this_day.py` + `bin/create_gmail_draft.py`.

---

## infra / ops — *do first; the agent needs these to verify its own work*

1. **P1 · S · infra** — pytest + a `tests/` scaffold. Cover `analysis/utils` (`clean_text`,
   `chunk_text`), `scraper/utils` (`slugify`, `is_article_url`), and the corpus-fingerprint
   helper. → seeds `make test`. *(Pre-baked: `plans/ready/0001-verification-infrastructure.md`.)*
2. **P1 · S · infra** — ruff lint+format config in `pyproject.toml` + `make lint` / `make fmt`.
3. **P1 · S · infra** — `make verify` = lint + tests + dashboard smoke build. This is the
   command the daily agent's §7 fast-verification should prefer once it exists.
4. **P2 · M · infra** — GitHub Actions CI running `make verify` on every PR. *(queued: ready/0002)*
5. **P3 · S · infra** — pre-commit hooks (ruff + JSON validity check on `data/analysis/*.json`).
6. **P2 · M · ops** — conductor preflight as a reusable Python helper (one health check,
   clear error message) shared by every module instead of ad-hoc curl in `weekly_run.sh`.
7. **P3 · M · ops** — structured logging across analysis modules (replace `print`) + `--verbose`.

## scraper

8. **P2 · S · scraper** — manifest integrity checker: detect orphaned `data/raw/*.json`,
   missing/duplicate `content_hash`, manifest/disk drift. Surface as a `make` target.
9. **P2 · M · scraper** — coverage audit vs the Forbes author index: report missing date
   ranges / slugs so we know what the archive is still missing.
10. **P3 · M · scraper** — richer metadata per article: canonical URL, original-vs-updated
    date, section, byline variants.

## analysis

11. **P1 · L · analysis** — prediction-verdict **backfill**: a web-search-augmented T3 pass to
    propose verdicts, plus a tiny JSON-edit adjudication CLI so the family can confirm/override.
    This is the "slow part" that makes Track Record fully alive. *(queued: ready/0004)*
12. **P2 · M · analysis** — confidence calibration for Track Record: hit-rate by confidence
    language (hedged/confident/certain), Brier-style scoring, "most right / most wrong" boards. *(queued: ready/0004 deepen)*
13. **P2 · M · analysis** — "intellectual arc": theme evolution year-over-year with a
    generated narrative of how his focus shifted.
14. **P2 · L · analysis** — entity co-occurrence graph (people/orgs) feeding a new dashboard
    network viz. Builds on `entities.py`.
15. **P3 · M · analysis** — contradiction / mind-change finder: where did he revise a view?
16. **P3 · S · analysis** — "Calhoun-isms": most quotable/aphoristic sentences per theme.
17. **P2 · M · analysis** — per-entity stance over time (e.g. his evolving view of the Fed,
    Bitcoin, the ECB).

## dashboard / family-facing

18. **P2 · S · dashboard** — "Ask Dad" chat persistence (localStorage) + transcript export. *(queued: ready/0005)*
19. **P2 · M · dashboard** — Ask Dad citations deep-link into the Raw Corpus tab and highlight
    the matched passage. *(queued: ready/0005 deepen)*
20. **P2 · M · dashboard** — mobile-responsive pass (the family will open this on phones). *(queued: ready/0006)*
21. **P3 · M · dashboard** — "Reading room": clean, paginated full-article reader with
    prev/next and theme tags.

## family

22. **P1 · M · family** — On This Day **auto-send** (beyond draft): configurable recipient
    list + a pre-send editorial override step. Builds on `on_this_day.py` + D9. *(queued: ready/0003)*
23. **P3 · M · family** — annual "year in review" digest email (best predictions, top themes).
24. **P3 · M · family** — printable/PDF "best of" anthology generator.

## training / ML

25. **P1 · M · training** — RAG faithfulness eval harness: held-out articles, measure Ask Dad
    citation accuracy and hallucination rate. Establishes the baseline before any fine-tune. *(queued: ready/0007)*
26. **P2 · L · training** — finish `notebooks/finetune_qlora.ipynb` → a reproducible training
    script + voice-fidelity eval vs the RAG baseline.
27. **P3 · M · training** — embedding-model comparison before ever changing the pinned model (D2).

## docs

28. **P3 · S · docs** — "how to add a new analysis module" runbook + a formal written
    conductor-contract doc (chat/embeddings signatures, tiers, error modes).
