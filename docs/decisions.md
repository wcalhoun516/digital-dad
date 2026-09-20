# Decisions (ADR-style log)

Non-obvious choices and *why*. Check here before reversing something that looks odd. Newest
entries can go on top. These reconstruct the rationale of the existing codebase plus the
choices made setting up the daily agent.

---

### D1 — All LLM calls go through a local "conductor", not provider SDKs directly
**Why:** decouples analysis code from any one model/provider and centralizes cost control,
model pinning, and API keys. Code just asks for a *tier* and *function*; the conductor routes.
**Implication:** the project depends on the sibling `local-llm-conductor` running at
`127.0.0.1:8080`. If it's down, analysis and Ask Dad fail loudly — that's intended.

### D2 — The embedding model is pinned (`sbert-mpnet-v2`)
**Why:** cosine similarity is only meaningful within a single vector space. Semantic Search,
Ask Dad retrieval, and On This Day matching must all use the *same* embeddings, so the model
is pinned and the embedding cache is busted on a corpus-or-model hash change.
**Implication:** don't swap the embedding model casually — it invalidates the whole index and
breaks cross-feature comparability. Evaluate alternatives first (roadmap #27).

### D3 — Corpus fingerprinting drives skip logic
**Why:** re-running expensive analysis (especially LLM passes) on an unchanged corpus is
wasteful. An MD5 over slugs+content_hashes gates each module via `data/analysis/runs.jsonl`.
**Implication:** if analysis "didn't run," check the fingerprint — use `--force` to override.

### D4 — The dashboard is fully client-side (vanilla JS + D3, no build step)
**Why:** maximum durability and zero ops. A single `index.html` with data baked in opens
anywhere, forever, with no server to maintain. The only live dependency is the conductor for
Ask Dad/search, and the rest degrades gracefully without it.
**Implication:** no framework, no bundler. Keep additions to plain JS/D3 unless there's a
strong reason to introduce a toolchain (which would undercut the durability goal).

### D5 — Three-tier scraper fallback (Playwright → sitemap/requests → Wayback)
**Why:** Forbes is hostile to scraping and articles disappear. Wayback is the resilient
backstop; requests is cheapest; Playwright handles JS-rendered pages. Rate-limited + retried.
**Implication:** ingestion is slow but robust. Don't remove the Wayback path.

### D6 — Local-first LLM tiering (T2 default, T3 opt-in)
**Why:** the corpus is large and analysis is repeated weekly; running on a free local model
keeps it sustainable. Paid T3 (OpenRouter) is reserved for quality-sensitive passes via
`--remote` or the dashboard toggle.
**Implication:** default runs are free but lower-fidelity; reach for T3 deliberately.

### D7 — Raw article text is gitignored
**Why:** licensing/copyright. The repo's value-add is analysis and structure, not
redistribution of Forbes content. `data/raw/*`, embeddings, and training artifacts stay local.
**Implication:** a fresh clone has no corpus until `make scrape` runs.

### D8 — Psychoprofile uses map-reduce; predictions use extract-then-verify
**Why:** both keep within context limits, are resumable, and produce auditable intermediate
artifacts. Map-reduce: per-batch analysis → one synthesis. Predictions: per-article
extraction → batched verdict pass, saved incrementally.
**Implication:** long jobs survive crashes; partial results are valid.

### D9 — Email is a Gmail-MCP *draft*, not SMTP auto-send
**Why:** keeps a human in the loop for anything family-facing, and avoids storing mail
credentials. `create_gmail_draft.py` hands the rendered email to Claude Code's Gmail MCP.
**Implication:** On This Day does not send on its own (yet — roadmap #22).

### D10 — Scheduling is launchd; the repo lives on an external volume
**Why:** the Mac mini host keeps the corpus on `/Volumes/FamilyWorkDrive`. launchd is robust
to sleep (runs missed jobs on wake). The external volume means scheduled jobs must wait for
the mount and need Full Disk Access granted to their interpreter.
**Implication:** scheduled scripts use a trampoline staged on the system disk and a mount
wait; `/bin/bash` needs a one-time FDA grant.

### D11 — A daily product-dev agent, separate from the weekly data refresh
**Why:** two different jobs. Weekly (`bin/`, Sun 03:00) refreshes *data*. Daily (`scripts/`,
01:00) improves the *product* by opening one small reviewable draft PR. Keeping them separate
keeps each simple and lets the daily agent be forbidden from touching the weekly job.
**Implication:** the daily agent never merges, never pushes to `main`, and never edits its own
scheduler or the weekly cron. Its envelope is structural (see `daily_routine_prompt.md` §11).

### D12 — Daily agent permission envelope is *structural*, not content-based
**Why:** the owner wants it to function as a genuine automated product-dev system across the
whole codebase — nothing is off-limits to *edit*. Safety comes from git/process guardrails
(no merge, no push to main, no force-push/reset, no self-modifying scheduler, no touching
other `daily/*` branches, leave the human-curated roadmap/changelog alone), not from
file bans.
**Implication:** review the draft PR each day — that's the safety net, by design.

### D13 — Mobile-responsive is CSS-foundation-first; D3 chart resize deferred
**Why:** the family opens the dashboard on phones (roadmap #20). The cheap, low-risk,
high-coverage win is a media-query layer (scrollable tab bar, fluid padding/type, single-
column grids, horizontally-scrollable tables) plus making fixed-size SVGs scale via `viewBox`.
The theme-map and linguistic charts already size from their container; only the radar was
fixed (now `viewBox`-scaled). Re-rendering D3 charts on resize/orientation change is a
separate, heavier slice (plan 0006 step 2) that genuinely needs live-browser verification.
**Implication:** the CSS layer lives behind `@media` guards in `dashboard/template.html`
(no desktop regression) and is locked in by `tests/test_dashboard_responsive.py`. A future
run does step 2 (container-driven re-render) with real device/preview screenshots.

### D14 — D3 resize-redraw re-renders the active tab; only the stateless chart tabs
**Why:** plan 0006 step 2. The pixel-sized charts (theme map, timeline) read their container
width once, at render time, so a window resize / phone orientation flip left them at stale
dimensions. Rather than teach each chart a bespoke "update geometry" path, a single debounced
`resize` handler just re-renders the active tab (it already measures the container on entry).
Two consequences had to be designed for: (1) re-rendering must be **idempotent**, so each
chart now clears its SVG (`selectAll('*').remove()`) and rebuilds its legend, and the timeline
toggle uses `onclick =` (assignment replaces) instead of `addEventListener` (which would stack
a duplicate handler per redraw); (2) redraw is **restricted to a `RESIZE_REDRAW_TABS` set
(`themes`, `timeline`)** — re-rendering an interactive tab (Ask Dad chat, Corpus filters) would
wipe the user's in-flight state. The radar and linguistic charts already scale via `viewBox`
(D13), so they're intentionally left out of the redraw set.
**Implication:** locked in by `tests/test_dashboard_responsive.py`. Adding a new chart tab that
needs resize behavior means making its render idempotent first, then adding it to the set.
**Still pending:** a live phone-width browser pass (headless run, no preview tooling) — a
reviewer should rotate/resize a real viewport before merging. Plan 0006 steps 3–4 (table
reflow, dual-breakpoint device verification) remain.

### D15 — RAG is the product voice; the QLoRA fine-tune stays experimental (26f)
> **Superseded in part by [D17](#d17--the-fine-tunes-problem-was-never-the-data-shape-rag-stays-the-voice) (2026-09-19).**
> The *verdict* below stands and is now better evidenced. The **revival path** it
> prescribes — "more examples-per-article (138 → 500+) plus more iters / higher LoRA
> rank" — was tested and **did not work**. Do not start from it.
**Why:** the first real Geo-LLM adapter (Qwen2.5-3B QLoRA, 138 training examples, plan 0008
26c/26e) was scored by the 26d blind voice-fidelity eval against the RAG "Ask Dad" answer and a
genuine Calhoun excerpt. Result (8 held-out prompts, T3 judge): **fine-tune 0% win-rate, avg
rank 2.88 — last in every trial**, while RAG (1.50) and real (1.63) tied at the top. Crucially
the judge could **not** distinguish RAG answers from real excerpts (50/50), validating the
retrieval path. Style metrics explain the loss: the fine-tune's lexical diversity (type-token
ratio 0.35) is half the real corpus (0.70) and it over-uses his distinctive vocabulary at ~2×
the natural rate (101 vs 46 hits/1k) — it learned surface markers, not fluency, and (ungrounded)
it hallucinates specifics.
**Implication:** Ask Dad (RAG) remains the trustworthy, shipped voice; the fine-tune is **not**
registered in the conductor and the dashboard's Ask Dad fine-tune toggle stays hidden (no
`geo_llm_registration.json` marker dropped). Reviving the fine-tune requires the data lever
first: more examples-per-article (138 → 500+, a 26a change) plus more iters / higher LoRA rank,
then re-run `make voice-eval`. The adapter, trials, and eval report live under
`data/finetune_run/` and `data/analysis/voice_eval.*` (all gitignored). Mild overfitting
appeared by iter ~100 (val loss bottomed there), consistent with the tiny training set.

### D20 — In-context exemplars beat fine-tuning, and the adapter fights them.
**Date:** 2026-09-19. Closes roadmap **#53/#58**. Extends D19 with the owner's design:
one model, four conditions, plain-vs-fine-tuned throughout.

**Setup.** Gemma 4 e4b throughout. Long run on the boilerplate-pruned corpus (#59): 2000
iters, best val **2.956 @ iter 400**, final 4.139, final train **1.211** — a 2.9 train/val gap,
outright memorization. **The bottom arrives at 0.74 epochs, before the model has seen the
corpus once.** Evaluated at iter 400, never the final adapter. 50 exemplars (~24k tokens,
train-split only, 8-gram-checked against heldout). Length-matched generation. Four 3-way blind
rankings, 8 held-out prompts, T3 judge.

| experiment | fine-tuned | plain | ft beats plain |
|---|---|---|---|
| A — no retrieval | 2.50 | 2.50 | 50% |
| B — + retrieval | 2.62 | **2.38** | 38% |
| C — + 50 exemplars | **2.88** | **2.12** | **12%** |
| D — exemplars + retrieval | 2.50 | 2.50 | 50% |

`real` won **100% of every experiment** — no arm is close to passing for his actual prose.

**Finding 1 — exemplars are the best lever measured, on the *plain* model.**
`gemma-plain-shot` at **2.12** is the strongest non-real arm across every run to date, better
than plain (2.50) and plain+RAG (2.38). Fifty well-chosen passages in context beat both
fine-tuning and retrieval.

**Finding 2 — the adapter actively fights the exemplars.** `gemma-ft-shot` at **2.88** is the
*worst* arm measured, worse than the fine-tune without them (2.50). In condition C the plain
model beats the fine-tuned one **88% of the time**. The fine-tune has overwritten the very
behaviour the exemplars are trying to induce, so adding them makes it worse, not better.

**This is why the plain-shot control existed.** Had we run only the two arms originally asked
for (`ft-shot`, `ft-shot-rag`), C would have read "exemplars hurt" — exactly backwards. D19's
lesson applied.

**Finding 3 — exemplars and retrieval are not additive.** Condition D washes both back to 2.50.
They compete for the same job: showing the model how to write. Stacking them buys nothing.

**Style metrics, consistent across all four:**

| arm | TTR | Δ distinctive/1k vs real |
|---|---|---|
| real | 0.692 | — |
| gemma-plain | 0.743 | +0.6 |
| gemma-plain-shot | 0.727 | −1.9 |
| gemma-plain-rag | 0.689 | −7.5 |
| gemma-ft | **0.353** | **+49.0** |
| gemma-ft-shot | **0.314** | +24.0 |

Every *plain* arm sits on top of real (TTR 0.69–0.78, distinctive vocabulary within ±8). Every
*fine-tuned* arm halves lexical diversity and over-produces his topic vocabulary. Notably,
exemplars **partially** repair the vocabulary damage (+49 → +24) but cannot restore diversity —
the adapter's flattening is not recoverable in-context.

`gemma-plain` is startlingly close to real on every style axis: TTR 0.743 vs 0.692, distinctive
+0.6, sentence length 25.3 vs 25.2. The style metrics cannot separate them; only the judge can.

**Implication.** Stop fine-tuning on this corpus. The shipped voice stays RAG, and the most
promising unexplored direction is **more and better in-context material** — which the 262k
context makes cheap and which improves automatically as the corpus grows. Roadmap #54 (DAPT)
and #55 (preference pairs) remain open as *different objectives*, but LoRA instruction-tuning at
this corpus size is now measured three times and has never once helped.

**Recorded to the series.** 12 rows in `data/analysis/voice_eval_history.jsonl`, each carrying
corpus size (181 articles / 340,849 words / ~453k tokens) beside the score, per #60. Re-run
`make voice-candidates` + `voice_eval` as the corpus grows; the curve is the product claim.

**Two process notes, both mine.** A 35-minute stall was a hung HuggingFace hub socket in
`CLOSE_WAIT` during model load — use `HF_HUB_OFFLINE=1` when weights are cached. And a complete
8-arm generation run was discarded by the completeness guard tripping on vestigial placeholder
keys *after* all work finished; the generator now persists after every arm.

---

### D19 — Fine-tuning makes it *worse*. The control arm settles it.
**Date:** 2026-09-19. Closes roadmap **#50**. Supersedes D17's open question; D15/D17's
product verdict (RAG is the voice) stands and is now properly controlled.

**What D17 could not answer.** D17 compared a Qwen **3B with no context** against a Gemma
**12B holding 8 retrieved passages** — a 4x parameter gap plus a retrieval advantage — so "the
fine-tune lost" could not be separated from "a 3B model lost". The owner called this out and
specified the right design: hold the model constant, vary only tuning and retrieval.

**Design.** One model throughout — Gemma 4 e4b (7.46B, `mlx-community/gemma-4-e4b-it-4bit`),
LoRA on 16 of 42 layers, rank 16, 300 iters, best checkpoint by val loss (iter 260).
Generation matched for length (220-token cap, 1.1 repetition penalty) against ~134-word
reference excerpts. Retrieval cached before training so memory never competed. Two 3-way blind
rankings, 8 held-out prompts each, T3 judge.

*Intended* base was tier 2's own `gemma4:12b-it-qat`. **Not possible:** every MLX conversion of
Gemma 4 12B (12 repos checked) declares `model_type: gemma4_unified`, and mlx-lm implements no
`gemma4_unified` in 0.31.3 **or on upstream main**. e4b is plain `gemma4`, same generation, and
already in the owner's Ollama roster. So this measures e4b, not the 12B serving tier 2.

**Experiment A — no retrieval**

| arm | win-rate | avg rank | TTR | fingerprint/1k |
|---|---|---|---|---|
| real | 100% | 1.00 | 0.709 | 28.1 |
| gemma-plain | 0% | 2.25 | 0.757 | 37.1 |
| gemma-ft | 0% | **2.75** | **0.220** | 48.5 |

**Experiment B — with retrieval**

| arm | win-rate | avg rank | TTR | fingerprint/1k |
|---|---|---|---|---|
| real | 88% | 1.12 | 0.709 | 28.1 |
| gemma-plain-rag | 12% | 2.25 | **0.762** | **23.0** |
| gemma-ft-rag | 0% | **2.62** | **0.280** | **98.1** |

**The finding: the adapter is a net negative.** Head-to-head, the *un-tuned base beats its own
fine-tuned self* — **75%** without retrieval, **62%** with. The question was never "did the
fine-tune win"; it is "the fine-tune costs you something", and it costs you in both conditions.

**It is not a Qwen artifact.** The same failure mode reproduced on a different, larger base:
lexical diversity collapses (TTR 0.22–0.28 against real's 0.709) while his distinctive
vocabulary is over-produced — **98.1 per 1k against real's 28.1, a 3.5x over-use**. Two
architectures, two parameter scales, one behaviour.

**And it is NOT overfitting.** Val loss was still *descending* at the best checkpoint (3.074 @
iter 260 from 4.655), and final train loss 3.233 sits essentially on top of val 3.186 — no
memorization gap at all, unlike the Qwen run's train 1.845 vs val 3.058. The adapter was
**underfit and harmful at the same time**. That matters: "train longer" and "add more tokens of
the same kind" are not obviously the fix, because the model was not failing to fit — it was
fitting the wrong thing.

**Diagnosis.** Instruction-pair fine-tuning on ~453K tokens optimizes the cheapest available
loss reduction: reproduce the surface markers of his prose. That is exactly what the metrics
show — hinge vocabulary up 3.5x, lexical variety down two-thirds. The objective is teaching
mimicry, not voice.

**Implication.** Ask Dad (RAG) remains the shipped voice, and the fine-tune should not be
registered in the conductor. Note how close the *plain* model plus retrieval sits to the real
thing on style: TTR 0.762 vs 0.709, fingerprint 23.0 vs 28.1 — slightly *under*-using his
vocabulary rather than over-using it. Retrieval is doing real work (plain-rag took a win off
`real`; plain took none).

**What to try instead of more of this.** Not more iterations, not more rank, not more
instruction pairs:
1. **Many-shot in-context.** Gemma 4 carries a 262K context and the entire corpus is ~453K
   tokens — over half of everything he wrote fits in one prompt. No training, and it cannot
   invent positions.
2. **DAPT** — continued pretraining on raw prose rather than instruction pairs, so the
   objective stops rewarding format mimicry.
3. **Synthetic preference pairs (DPO/ORPO)** — his passage vs a blandly rewritten one. The one
   technique that manufactures signal from the corpus already in hand.
4. **Better retrieval** — reranking, hybrid BM25+dense. Improving the arm that is winning.

Artifacts: `data/analysis/voice_eval_exp{A,B}.md` (committed). Training log:
`logs/gemma4e4b_20260919_133400.log`. Corpus at time of measurement: **181 articles,
340,849 words, ~453K tokens** — record this beside every future score.

---

### D17 — The fine-tune's problem was never the data *shape*. RAG stays the voice.
**Date:** 2026-09-19. **Supersedes D15's revival path** (not its verdict). Closes roadmap #40,
plan 0009 step 4–5.

**What was tested.** D15 blamed the fine-tune's loss on too few examples and prescribed
"138 → 500+ examples, more iters, higher LoRA rank". Plan 0009 found a sharper cause: every one
of the 138 records exceeded `max_seq_len`, so only ~33% of the corpus ever reached the model and
all of it was article *openings*. PR #91 reshaped the dataset into passage-level records. This
run re-tested the fine-tune on that clean data.

| | D15 run | this run |
|---|---|---|
| train / valid records | 138 / 34 | **544 / 130** |
| records over `max_seq_len` | 138/138 (100%) | **0/674 (0%)** |
| corpus reaching the model | ~33% | **100%** |
| iters | 200 | 1600 (~2.9 epochs) |

Everything else held identical — Qwen2.5-3B-Instruct-4bit, LoRA rank 8, 8 layers, lr 1e-4,
batch 1, seed 42 — so the variable under test was the data, not the recipe. `iters` scaled with
the dataset because holding it at 200 would have shown the model a *smaller* fraction of the
corpus, not a fairer test.

**Result: the hypothesis is falsified.** Blind A/B/C, 8 held-out prompts, T3 judge:

| source | win-rate | avg rank | | D15 |
|---|---|---|---|---|
| real | 75% | 1.25 | | 1.63 |
| rag | 25% | 1.75 | | 1.50 |
| **finetuned** | **0%** | **3.00** | | 2.88 |

The fine-tune placed **last in all 8 trials** — marginally *worse* than D15's 2.88, where it at
least sometimes placed second. Fixing the truncation did not help.

**Val loss bottomed at iter 100 — exactly where D15's run bottomed on a quarter of the data.**
It then degraded to 3.058 by iter 1600, *above* the 3.026 starting point, while train loss fell
to 1.845. Quadrupling the examples did not delay overfitting at all.

**Why, and this is the load-bearing insight.** The 544 records are chunks of the same **181
articles**. Example *count* quadrupled; distinct *material* did not. The model saw the same
corpus sliced finer, and overfit it on the same schedule. For the product thesis in `goals.md`,
this is the sharpest lesson available: **"enough text" means enough distinct source material,
not more examples carved from the same material.** Chunking is necessary — a truncated dataset
is strictly worse — but it is not a substitute for corpus.

**The failure mode also changed, for the worse.** D15's model over-used his vocabulary (~2×) and
hallucinated specifics. This one **loops** — it degenerates into repetition and runs to the token
cap. The worst case is *"been trying to gain access to American technology"*, repeated **13 times
inside a single sample** (trial v04, the semiconductors prompt); other trials loop on different
phrases ("was seen as a necessary step to restore market confidence…"). An earlier draft of this
ADR said "13 times across 8 samples", which overstated how systemic it is — the collapse is real
but localized. Length-controlled type-token
ratio is 0.459 against real's 0.724 and RAG's 0.716.

**Caveats, stated because they bound the claim.** Generation was capped at 400 tokens with no
repetition penalty, and the fine-tune wrote ~357 words against real's ~134 — length was not
matched. Raw TTR (0.197) is therefore unfairly low; the length-controlled 0.459 is the honest
number, and it is still far below both comparators. A rerun with a repetition penalty and
length-matched generation is a cheap sanity check worth doing before anyone calls this final.
n=8, one judge — matched to D15's protocol for comparability, not large.

**⚠ The comparison is confounded, and the "corpus diversity" conclusion above overreaches.**
Tier 2 resolves to **`gemma4:12b-it-qat`**. So the arms were:

| arm | model | context at inference |
|---|---|---|
| `rag` | **Gemma 12B** | 8 retrieved passages from his corpus |
| `finetuned` | **Qwen 3B** | none — working from weights alone |

That is a ~4× parameter gap *plus* a retrieval advantage, so this run does not isolate
fine-tuning. What it does establish is narrower and still decision-useful: **the fine-tune as
configured does not beat the shipped Ask Dad path**, which is the product question. The claim
that *corpus diversity* is the binding constraint is a hypothesis consistent with the val-loss
curve bottoming at iter 100 in both runs — it is **not** demonstrated here.

**Two controls are required before any further verdict.** Both are now reachable via
`make voice-candidates` (`analysis/voice_candidates.py`):

- **`base-3b`** — the same Qwen 3B, style prompt, *no adapter*. The single most important
  missing arm: it says whether fine-tuning helped, did nothing, or actively hurt. Without it,
  "the fine-tune lost" cannot be separated from "a 3B model lost".
- **`prompted-12b`** — tier 2 with a style prompt and *no retrieval*. Says how much of RAG's
  score comes from retrieval versus from simply being a 12B model.

A fair fine-tune test would also put the adapter on a comparable base — QLoRA on the 12B at
4-bit rank 8 is plausible on this hardware — so that it is fine-tune-vs-RAG on one model.

**Implication.** Ask Dad (RAG) remains the shipped, trustworthy voice, now on stronger evidence:
the judge ranked *real* above *RAG* 75/25 here, where D15 found them indistinguishable, so RAG is
not perfect either — but it is second to the real thing and the fine-tune is not close. The
adapter is **not** registered in the conductor and the dashboard toggle stays hidden.

**What is NOT the next lever:** more iterations, higher LoRA rank, or more chunking on this same
181-article corpus — tried twice, no movement. **What comes first:** the two control arms above,
which are cheap and decide whether fine-tuning is worth pursuing at all.
**What is likely after that:** more distinct material — the ingest arc (#33–#37) and source discovery (#49).
Re-run `make voice-eval` when the corpus has meaningfully grown, and record corpus size beside
the score so the "how much is enough" curve accumulates.

Artifacts: `data/analysis/voice_eval_reshaped*.md` (committed); adapters and trials are
gitignored. Training log: `logs/retrain_20260919_104018.log`.

---

### D16 — The lint gate covers the whole tree; E501 is carved out of the source packages
**Why:** `make lint` was scoped to `LINT_PATHS := tests` from the day it existed, so no
production line was ever linted — the deferral was recorded in the Makefile, the pre-commit
config, and roadmap #1–3, and PR #45 tripped over it from the far side (it ruff-fixed
`scraper/forbes_requests.py` and noted the file "was never gated"). Widening the scope
surfaced 98 findings, 24 of which were real: 9 dead imports, an unused local, two no-op
f-strings, an assigned lambda, an ambiguous `l`, and 10 unsorted import blocks.
**Implication:** all 24 are fixed and the gate now runs over `analysis scraper viz training
tools bin tests`. The remaining 74 are **E501**, and they are ignored *per-package* rather
than globally: most are embedded LLM prompt string literals (`psychoprofile` ×18,
`predictions` ×15, `on_this_day` ×11), and re-wrapping a prompt literal changes the prompt the
model actually sees — a behavior change masquerading as formatting, so it belongs in its own
reviewed pass. `tests/` is deliberately absent from `per-file-ignores`: it has been
E501-clean since the gate existed and stays fully gated, so this is a strict widening with no
rule weakened anywhere. `tests/test_lint_scope.py` pins all of that — it fails if a package
drops out of `LINT_PATHS`, if the pre-commit `files:` regex drifts out of lockstep with it,
or if `tests/` ever acquires a per-file ignore.

### D18 — Provenance is declared at the remote-call boundary, and silence means private
**Why:** tier 3 is OpenRouter — the only tier where corpus text leaves the Mac mini and
reaches a third party. Until roadmap #38 nothing checked *what* was being sent:
`analysis/predictions.py::_call` set `extra["allow_remote"] = True` for any `tier >= 3` and
posted the prompt. That was harmless only because the corpus was 204 scraped Forbes columns,
all already public. The ingest arc (#29–#35) exists specifically to end that: letters, emails
and books are `privacy: private` by default in `ingest/provenance.py`, and the moment one is
accepted, "send the article body to the judge" silently becomes "send his private
correspondence to a vendor".
**Implication:** `analysis.conductor.assert_remote_allowed(sources)` runs inside `_call`,
before the retry loop, and refuses outright. Three choices are load-bearing:

1. **The gate is in `_call`, not in a `make` recipe or each CLI.** `_call` is the single
   Python chokepoint that sets `allow_remote`; `verdict_backfill`, `voice_eval` and `rag_eval`
   all import it rather than building their own request, so guarding it guards all four. A
   per-CLI check would be theatre — the same mistake plan 0009 step 2 made before PR #94 moved
   that gate into `prepare_mlx_data()`.
2. **It fails closed on silence.** `sources=None` — a caller that never said what it was
   sending — is refused, not waved through. `sources=[]` is the explicit, greppable way to
   say "this prompt contains no corpus material". Anything whose provenance cannot be read as
   exactly `"public"` (missing block, unknown vocabulary value, unrecognised slug) is treated
   as private. A guard that defaults to permissive protects nothing.
3. **Coarse declarations are allowed where precision is unavailable.** `predictions` and
   `rag_eval` know the slugs in their prompt and declare exactly those, so one private letter
   does not block an otherwise-public batch. `voice_eval`'s trial passages carry no slug, and
   `verdict_backfill`'s `chat(prompt)` seam has no prediction in hand, so both declare
   `corpus_provenance()` — the whole corpus. That is deliberately conservative: it can refuse a
   run it did not strictly need to, and `--judge-tier 2` keeps it working locally. Over-refusing
   costs an eval; under-refusing costs his privacy, permanently.

**Deliberately not covered:** the dashboard's Ask Dad tier toggle
(`dashboard/template.html` sets `allow_remote` client-side). That is the owner's own browser
talking to his own conductor, outside this Python path — it needs its own gate, tracked as
follow-up work, and this ADR does not claim to have closed it.
