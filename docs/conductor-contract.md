# The conductor contract

The **conductor** is a local, OpenAI-compatible LLM server at `http://127.0.0.1:8080/v1`,
implemented in the sibling repo `local-llm-conductor` (not in this tree). Every model call in
`digital-dad` — chat completions, embeddings, the browser's Ask Dad + Semantic Search — goes
through it. No API keys live in this repo; the paid tier's `OPENROUTER_API_KEY` lives in the
conductor's own `.env`.

This is the **formal reference** for that contract: exact call shapes, routing, return values,
and failure modes. For the one-paragraph overview and where it sits in the pipeline, see
[`architecture.md` §3](architecture.md). For how a module *uses* this contract in practice, see
[`runbooks/adding-an-analysis-module.md`](runbooks/adding-an-analysis-module.md).

> **Why an abstraction at all?** The conductor lets every module say "give me a text model at
> tier N" without hard-coding model names, keys, or routing. Swap the local model, change the
> remote provider, or add a tier — callers don't change.

---

## 1. Connecting

Callers use the `openai` Python SDK pointed at the conductor's base URL. There is **no shared
`conductor.py`** — each module defines a tiny local client factory (by convention
`_get_client()` / `_get_conductor_client()`):

```python
from openai import OpenAI

CONDUCTOR_URL = "http://127.0.0.1:8080/v1"

def _get_client():
    return OpenAI(base_url=CONDUCTOR_URL, api_key="local")
```

- The base URL is **hard-coded** per module (`analysis/semantic_search.py:32`,
  `analysis/predictions.py:22`, `analysis/psychoprofile.py:20`, …). There is no
  `CONDUCTOR_URL` / `OPENAI_BASE_URL` environment override today — if that ever changes, do it
  in one place and have callers import it.
- `api_key="local"` is a placeholder the SDK requires; the conductor ignores it for local
  tiers. (Real provider keys live in the conductor, never here.)
- The browser uses the same contract via `fetch` against the same base URL (see
  `bin/serve_dashboard.py` and the Ask Dad code in `dashboard/template.html`).

The SDK import is wrapped so a missing optional dependency fails with an actionable message
rather than an `ImportError` deep in a call:

```python
try:
    from openai import OpenAI
except ImportError:
    raise ImportError("openai package not installed. Run: pip install -e '.[analyze]'")
```

---

## 2. Chat completions

```python
response = client.chat.completions.create(
    model="auto",                       # IGNORED — see below
    max_tokens=max_tokens,
    messages=[{"role": "user", "content": prompt}],
    extra_body={"tier": 2, "function": "text"},
)
text = response.choices[0].message.content or ""
```

| Field | Value | Notes |
|-------|-------|-------|
| `model` | `"auto"` | **Ignored.** The conductor classifies on `(tier, function)` and picks the actual model. Pass `"auto"` by convention. |
| `messages` | OpenAI chat array | Standard `{"role", "content"}` shape. |
| `max_tokens` | int | Output budget. Modules pick per task (e.g. `4096` for extraction, `300`/`120` for short generations). |
| `extra_body.tier` | `2` or `3` | Routing tier — see §4. |
| `extra_body.function` | `"text"` | The capability class. Text generation is `"text"`. |
| `extra_body.allow_remote` | `True` | **Required to actually permit a paid T3 call.** Set it whenever `tier >= 3`. |

**Return shape.** A standard OpenAI `ChatCompletion`. Read text from
`response.choices[0].message.content` (may be `None` → coerce with `or ""`). Token usage is on
`response.usage` (`prompt_tokens`, `completion_tokens`).

### Which model actually ran (`model_used`)

`model="auto"` means the caller doesn't know the model up front. The conductor injects
`{"conductor": {"model_used": "..."}}` into the response; the OpenAI SDK exposes unknown
top-level fields via `model_extra` (pydantic v2). Capture it for run records / cost logs:

```python
extra = getattr(response, "model_extra", None) or {}
conductor_meta = extra.get("conductor") or {}
model_used = conductor_meta.get("model_used") or response.model or "unknown"
```

Reference implementation: `analysis/psychoprofile.py:_call_conductor` (returns
`(text, prompt_tokens, completion_tokens, model_used)`).

### Retry convention

There is no shared retry wrapper; the established pattern (from `analysis/predictions.py:_call`)
is a 3-attempt loop with linear backoff, re-raising on the final failure:

```python
for attempt in range(3):
    try:
        response = client.chat.completions.create(...)
        return response.choices[0].message.content or ""
    except Exception as exc:
        if attempt < 2:
            time.sleep(5 * (attempt + 1))   # 5s, 10s
        else:
            raise
```

---

## 3. Embeddings

```python
EMBED_MODEL = "sbert-mpnet-v2"   # pinned — do not vary per call

resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
items = sorted(resp.data, key=lambda d: d.index)   # be defensive about order
vectors = [item.embedding for item in items]        # list[list[float]], 384-dim
```

- Unlike chat, embeddings pass an **explicit model id**, not `"auto"`. The conductor routes
  directly to that embedder, bypassing its smart-routing classifier
  (`analysis/semantic_search.py:28-31`).
- `input` may be a single string or a list; `resp.data` is index-aligned to the input. Sort by
  `.index` before reading vectors (defensive; the API returns them ordered).
- Output dimensionality for `sbert-mpnet-v2` is **384**.

### The embedder is pinned — and why it matters

`EMBED_MODEL = "sbert-mpnet-v2"` is a **project-wide invariant**, not a per-caller choice.
Cosine similarity is only meaningful **within one model's vector space**: the cached index
(`data/analysis/embeddings.npy`), every Ask Dad query, Semantic Search, and On This Day must
all embed with the same model. The model id is folded into the corpus fingerprint
(`analysis/semantic_search.py:_corpus_hash`, line 89) so **changing `EMBED_MODEL` invalidates
the cache and forces a full re-embed**, even when the dimensions still match.

Changing the embedder is roadmap **#27** and a deliberate, audited decision — never an
incidental edit.

---

## 4. Tiers and routing

The caller never names a model. It declares **intent** — a `function` and a `tier` — and the
conductor maps that to a concrete model.

| Tier | Backing | Cost | Selected by | Used for |
|------|---------|------|-------------|----------|
| **T1** | `phi3:mini` | ~free | (not actively wired in this repo) | cheap rewrites / query expansion |
| **T2** | local reasoning model | free | **default** | the analyze pipeline's LLM work (psychoprofile, predictions, On This Day) |
| **T3** | OpenRouter (remote) | **paid** | `--remote` flag / dashboard tier toggle; requires `extra_body.allow_remote=True` | the judge passes in the eval harnesses |

How `--remote` flows through the pipeline (`analysis/__main__.py`):

```python
router = "conductor_remote" if args.remote else "conductor_local"
# downstream: tier = 2 if router == "conductor_local" else 3
```

**Cost guardrail:** anything that can hit T3 is gated. The eval/backfill CLIs refuse to run
unless the conductor is reachable *and* the owner opted in, precisely because T3 calls cost
money (see §5 and `analysis/rag_eval.py`, `analysis/voice_eval.py`,
`analysis/verdict_backfill.py`). Unattended automation must never trigger an unguarded paid
call.

---

## 5. Error modes & reachability

### Health check before paid / batch work

Modules that make many or paid calls **preflight** the conductor and abort cleanly if it's
down, rather than failing mid-batch. The canonical helper (duplicated in `rag_eval.py:355`,
`voice_eval.py:448`, `verdict_backfill.py:223`):

```python
def _conductor_up(url: str = "http://127.0.0.1:8080/v1") -> bool:
    import urllib.error
    from urllib.request import urlopen
    try:
        with urlopen(url.rstrip("/") + "/models", timeout=4) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False
```

Convention for the owner-gated eval CLIs: if `not _conductor_up()`, print a clear message and
**return exit code 2** (the input is left untouched, no partial writeback). Missing input file
→ exit `1`; success → `0`.

### In-request failures

- **Chat:** transient errors are retried (§2). A hard failure re-raises — let it propagate in
  batch jobs so the run record reflects reality; in best-effort spots (e.g.
  `on_this_day.py:_generate_blurb`) it's caught, a warning printed, and an empty string
  returned.
- **Browser path:** `bin/serve_dashboard.py` translates a conductor-unreachable exception into
  an HTTP **502** with a JSON error body, so Ask Dad degrades visibly instead of hanging.

### Operational recovery (out of band)

The weekly cron (`bin/weekly_run.sh`) does its own health check by POSTing a tiny embeddings
request; on failure it clears stale SQLite WAL/SHM files and restarts the conductor via
`launchctl`. That recovery lives in the cron, not in module code — application code only
*checks* reachability, it does not restart the daemon.

---

## 6. Quick checklist for a new caller

1. Add a `_get_client()` returning `OpenAI(base_url=CONDUCTOR_URL, api_key="local")`, guarding
   the import.
2. For text: `model="auto"`, `extra_body={"tier": 2, "function": "text"}`; read
   `choices[0].message.content or ""`. Default to **T2**; only reach for T3 behind an explicit
   owner opt-in *and* `allow_remote=True`.
3. For embeddings: pass `EMBED_MODEL` (`"sbert-mpnet-v2"`) — never a different embedder.
4. If you make many or paid calls, `_conductor_up()`-preflight and abort with a clear message
   (exit `2`) when it's down. **Never let unattended code make an unguarded paid T3 call.**
5. Capture `model_used` if you keep a run/cost record.
