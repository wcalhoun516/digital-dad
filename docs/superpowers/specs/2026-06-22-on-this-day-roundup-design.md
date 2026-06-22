# Design — On This Day "in his words" weekly roundup

**Date:** 2026-06-22
**Status:** approved (design), pending implementation plan
**Touches:** `analysis/on_this_day.py` (+ tests). Delivery (cron + `weekly-on-this-day-draft` routine) unchanged.

## Goal

Add a top **roundup** section to the weekly On This Day email: up to ~6 of the past week's
headlines that have a *genuine* tie to Dr. Calhoun's past work, each with a one-sentence note
in his voice and a citation. Below it, keep the existing single-article **deep-dive** unchanged.
Precision over recall — only surface a headline if the connection is real, so nothing weak is
ever put in his voice (the project's "evidenced, not hallucinated" ethos).

## Behavior

**Layout (top → bottom):**
1. **"This Week — In His Words"** (new): for each qualifying headline, render the headline, a
   1–2 sentence in-voice connection, and a citation (article title, year, Forbes link).
2. **"From the Archive"** (existing deep-dive): the single strongest headline↔article match with
   the longer in-voice intro + full article body. Unchanged.

**Selection rules:**
- Fetch a larger candidate pool (up to ~20 headlines across the existing RSS feeds), embed each
  (pinned `sbert-mpnet-v2` via the conductor), and score against every article by cosine
  similarity — reusing the current machinery.
- **Deep-dive** = the global best (headline, article) pair (as today).
- **Roundup** = the *other* headlines whose best-match cosine similarity is **≥ 0.55**, sorted
  strongest-first, **capped at 6**, with two dedup guards:
  - never include the deep-dive's article;
  - if two headlines map to the same article, keep only the higher-scoring headline.
- **Empty case:** if nothing else clears 0.55, omit the roundup section entirely — the email
  falls back to today's deep-dive-only format. The build/render must never fail on an empty
  roundup.

**Blurbs:** one **free local tier-2** conductor chat per roundup item (same tier as the current
intro), prompting for a single tight sentence on why his article connects to that headline,
written in the first person. ~6 extra free calls/week. A blurb that fails to generate (or comes
back empty) drops that item rather than shipping a blank.

## Code shape (`analysis/on_this_day.py`)

Factor the matching into a **pure, offline-testable** function and keep IO at the edges:

- `select_matches(headlines, article_vectors, *, threshold=0.55, cap=6) -> {deep_dive, roundup}`
  — pure: takes pre-computed headline embeddings + article vectors (or a score matrix), returns
  the deep-dive pair and the ordered, deduped, capped roundup list. No network. This is the
  unit under test.
- IO seams unchanged in spirit: `_fetch_headlines` (RSS), `_embed_one`/`build_embeddings`
  (conductor), `_generate_intro` (deep-dive) + new `_generate_blurb` (roundup, 1 sentence),
  and the HTML renderer (new roundup block above the existing deep-dive block).
- `run()` orchestrates: fetch → embed → `select_matches` → generate intro + blurbs → render →
  log to `data/cron/on_this_day.jsonl` → write `data/cron/emails/on_this_day_<date>.html`.

Thresholds/caps are module constants (`ROUNDUP_THRESHOLD = 0.55`, `ROUNDUP_CAP = 6`) so they're
easy to tune.

## Delivery — no change

The weekly cron (`make on-this-day`) and the `weekly-on-this-day-draft` routine both
render-then-draft whatever `run()` produces; they are format-agnostic and pick up the new
section automatically. Verification will confirm the enhanced HTML still flows through
`bin/create_gmail_draft.py --json` (→ `to`/`subject`/`html_body`) cleanly.

## Testing

- **TDD `select_matches()`** on fixture vectors: deep-dive = global best; roundup applies the
  0.55 threshold; excludes the deep-dive article; dedups same-article headlines (keeps stronger);
  caps at 6; sorts strongest-first; returns empty roundup when nothing qualifies.
- **Render smoke:** build an email from a stubbed multi-item roundup; assert both sections appear
  and the citation/link markup is present; build one with an empty roundup and assert only the
  deep-dive renders and no error is raised.
- **Delivery smoke:** `create_gmail_draft.py --json` still produces a valid payload from the new
  HTML.

## Non-goals

- No change to the deep-dive logic, the RSS feed list, the embedding model, or the delivery /
  approval-gate (D9) mechanism.
- No new dependencies; blurbs stay on the free local tier (no paid T3).
