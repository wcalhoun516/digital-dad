# Plan 0011 — Operator console: feed the corpus, turn the crank, keep score

## Status (refreshed 2026-09-21 — **steps 1–4 are complete, routes and page included**)

- **Step 1 — done and merged** (PR #93). Console shell, `/console/api/*` dispatch in
  `bin/serve_dashboard.py`, route gate, Funnel refusal.
- **Step 2 — done.** Validation core merged in PR #96 (`ingest/upload.py`: the sanitizer, the
  registry-derived extension allowlist, the size cap, the non-clobbering writer).
  **`POST /console/api/upload` written in PR #109** as the thin caller of `stage_upload` it was
  always meant to be, plus the one thing the module cannot do: refuse an oversize
  `Content-Length` *before* the body is read.
- **Step 3 — done.** Decision core merged in PR #97 (`apply_decision`, `edit_item`,
  `reject_item`, `validate_field`, `queue_view` / `item_view`, with `run_cli` rewired onto the
  same functions). **`GET /console/api/queue` and `POST /console/api/review` written in PR
  #109**, with `UnknownItem` → 404 and every other `ReviewError` → 400.
- **Step 4 — done** (PR #111). New top-level `console/` package: `console/jobs.py` is the
  one-job-at-a-time state machine, `POST`/`GET /console/api/job` and `GET
  /console/api/job/log` are the routes, and the page's step-4 placeholder is now a job panel
  with a live log. **The inbox note is gone** — uploading now points at the `ingest` button
  instead of at a terminal.
- **The page is wired for steps 2–4** (PRs #109, #111): upload picker, review queue with
  accept/edit/reject, and the job runner, each verified in a live headless-Chromium pass
  against the real server.
- **Steps 5–6 — not started.**

**Next run should do step 5, the scoreboard.** It is the point of the whole plan (see *Goal*
below) and now has everything it depends on: step 4 gives it the runs to score. Three things
it should know:

- **Read the run record, do not re-derive it.** `console/jobs.py` already persists every run
  to `data/console/job.json` with its job name, exit code, and timestamps. The scoreboard's
  "did this run beat the last one?" needs eval *results*, not job bookkeeping — resist the
  urge to grow the job record into a results store.
- **The eval numbers already exist.** `analysis/voice_eval.py` writes them; the scoreboard is
  a reader and a differ, not a new measurement.
- **`train` and `voice-eval` are `costly=True`** in the job registry and the page confirms
  before starting them. Anything the scoreboard adds that spends GPU hours or T3 dollars
  should carry the same flag rather than inventing a second mechanism.

**Two things step 4 decided that later steps inherit:**

- **The log is polled by byte offset, not streamed over SSE** (this plan's step-4 text
  suggested reusing `_proxy`'s SSE). An SSE tail holds one handler thread per viewer for the
  length of a training run and still needs tearing down when the job ends; a poll that says
  "I have the first N bytes" delivers each line exactly once, costs a stat and a seek, and
  survives a closed laptop. Step 5 should poll too.
- **Job liveness is re-derived from the pid on every read**, never trusted from the file. The
  state file outlives the server; the process does not.

**Rejects still live in the queue directory**, marked `status: rejected` with their reason.
Step 3's `data/ingest/rejected/` move is deliberately **not** done: it changes the on-disk
layout and makes `queue_summary`'s rejected count read from a second place, which deserves
its own slice rather than riding along on the decision core.

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
   *Done in PR #111, with one deviation: the log tail polls by byte offset instead of SSE —
   see the Status block for why. `ingest` was added to the registry as the button that
   replaces "run `make ingest` at a terminal".*
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
