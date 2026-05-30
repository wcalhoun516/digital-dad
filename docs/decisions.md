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
