# Plan 0011 — Operator console: feed the corpus, turn the crank, keep score

## Status (2026-09-13)

- **Step 1 — done, unmerged** (PR #93). Console shell, route gate, Funnel refusal.
- **Step 2 — validation core done, unmerged** (PR #96). `ingest/upload.py` holds the
  sanitizer, the registry-derived extension allowlist, the size cap and the non-clobbering
  writer, all tested. **The `POST /console/api/upload` route itself is NOT done** — it needs
  step 1's dispatch in `bin/serve_dashboard.py`, which is still unmerged. Do that wiring once
  #93 lands; it is a thin caller of `stage_upload`, not a reimplementation.
- **Steps 3–6 — not started.**

A daily run picking this plan up should start at the step-2 route wiring (if #93 has merged)
or step 3, and should **not** rewrite `ingest/upload.py`.

## Goal

A local web console for running the Geo-LLM flywheel without a terminal: drop files in, review
what was extracted, trigger the rebuild→train→eval cycle, and **see whether this run beat the
last one**.

Roadmap **#42**. Design:
[`superpowers/specs/2026-09-07-next-phase-design.md`](../../superpowers/specs/2026-09-07-next-phase-design.md).

The scoreboard is the point. Geo-LLM stalled because it was a one-shot experiment that failed
once and was shelved by an ADR — nobody could see whether a change helped. A flywheel needs a
dial.

## Context

**Host:** `bin/serve_dashboard.py` — 199 lines of stdlib `ThreadingHTTPServer`. It already
gates every request behind HTTP Basic Auth (`_gate()`, constant-time compare, refuses to start
without a password), already proxies `/v1/*` to the conductor **with SSE streaming**, and
already has a `do_POST` that 405s anything else. Console routes are a clean extension of an
existing, working surface: no framework, no build step, no new dependency.

**Relationship to D4.** D4 makes the *family dashboard* fully client-side for durability — one
`index.html` that opens anywhere, forever. The console has the opposite requirement: it writes
files and starts jobs, so it is inherently server-bound. Two surfaces, two jobs. The console
must never leak into the family artifact. **Record this as a new ADR** rather than leaving it
as a silent exception to D4.

**Existing pieces to reuse:** `ingest/queue.py` and `ingest/review.py` (the queue and the
accept/edit/reject decision logic already exist — the console is a second *front end* to them,
not a second implementation), `training/finetune_preflight.py`, `analysis/voice_eval.py` and
`analysis/rag_eval.py` (both already write report JSON), `data/inbox/` (the ingest front door).

### ⚠ Security — read before writing any route

`bin/serve_dashboard.py` is currently published to the **public internet** via Tailscale Funnel
on `:8443`, protected by a single shared password. Everything it serves today is *read-only*.
This plan adds **file upload** and **job execution**, which is a categorical escalation: a
guessed or leaked password would go from "reads the archive" to "writes files to disk and
starts processes on the Mac mini."

**Required:** serve the console on a **tailnet-only** listener (`tailscale serve`), not the
public Funnel. The family dashboard stays on the Funnel; the console does not. If that
separation cannot be made cleanly in one slice, the console must **refuse to start** when it
detects it is Funnel-exposed, rather than shipping reachable. Do not treat the existing
password as sufficient for write access.

This is a hard gate on the plan, not a nice-to-have. Raise it in the PR body explicitly so the
owner rules on it.

## Steps — each step is its own PR

Use `superpowers:test-driven-development`. Route dispatch, upload validation, and job-state
logic are all pure and testable offline; no test may start a real training run.

1. **Console shell + route gate (S).** A `/console` GET serving one static page from
   `dashboard/console.html`, plus `/console/api/*` dispatch. Prove by test that **every**
   console route passes through `_gate()` — an unauthenticated request to each must 401. Add
   the tailnet-only listener check from the security section; refuse to start if
   Funnel-exposed.
2. **Upload → inbox (M).** `POST /console/api/upload` writes into `data/inbox/`.
   **Validation is the whole job here:** extension allowlist (only registered handler formats),
   a size cap, and **filename sanitization** — reject path separators, `..`, absolute paths, and
   control characters; never trust the client-supplied name. TDD the sanitizer against
   traversal attempts first; it is the one piece of this plan where a bug is a real
   vulnerability rather than a defect. Files are written, never executed.
3. **Review queue (M).** `GET /console/api/queue` lists pending items from `ingest/queue.py`;
   `POST /console/api/review` applies accept/edit/reject **through `ingest/review.py`'s existing
   decision functions**. Per source, not per document — a book prompts once, not forty times.
   Rejects move to `data/ingest/rejected/` with a reason and are never deleted. Surface
   warnings first, then guessed metadata, then the first ~400 characters, mirroring the CLI.
4. **Job runner (M).** A small runner that executes a named pipeline step
   (`finetune-prep` → `finetune-preflight` → train → `voice-eval`) as a **subprocess**, writing
   to a log file, with state in one JSON file. **Never in the request handler.** One job at a
   time — a second trigger returns 409, it is not queued silently. `POST /console/api/job`
   starts, `GET /console/api/job` returns state, `GET /console/api/job/log` tails the log
   (reuse the existing SSE streaming pattern from `_proxy`). TDD the state machine with a fake
   subprocess; **no test starts a real job**.
5. **Scoreboard (M).** `GET /console/api/scores` reads the `voice_eval` / `rag_eval` report
   JSONs plus a small append-only run history and renders run-over-run deltas: win-rate, avg
   rank, TTR, hinge-word rate, and the preflight's over-budget percentage. **Show D15's numbers
   as the standing baseline** (fine-tune 0% win-rate, avg rank 2.88; RAG 1.50; real 1.63; TTR
   0.35 vs 0.70) so every future run is read against the record it has to beat.
6. **Docs + ADR (S).** README section, and the new ADR recording the console-vs-D4 split and
   the tailnet-only decision.

## Verification

- Auth: an unauthenticated request to **every** console route returns 401 — a table-driven test
  so a newly added route cannot skip the gate.
- Upload: traversal attempts (`../`, absolute paths, null bytes, separators) rejected; oversize
  rejected; disallowed extensions rejected — each proved red first.
- Job runner: state transitions and the 409-on-concurrent-start proved against a fake
  subprocess. No real training in any test.
- Review: a queue item accepted through the API produces the same result as the CLI path on the
  same fixture — the point is one decision implementation, two front ends.
- `make verify` green; paste real output per §7.
- Clear `__pycache__` before trusting any red→green proof (external-volume stale `.pyc`).
- The console page itself needs a **live browser pass** — `make verify-responsive` already
  drives headless Chromium and is the precedent. Screenshots in the PR.
- `superpowers:verification-before-completion` before flipping to ready.

## Out of scope

- Exposing the console on the public Funnel. See the security section — this is a refusal, not
  a deferral.
- Any authentication rework (accounts, sessions, OAuth). Basic Auth on a tailnet-only listener
  is the scope; a second factor is a separate decision.
- Changing the family dashboard. D4 stands; `index.html` remains static and self-contained.
- Running training on a schedule. Training is explicitly owner-triggered — hours of local GPU
  should not start because a cron fired.
- Deleting source material. Rejects move aside with a reason; nothing is destroyed from the
  console.
