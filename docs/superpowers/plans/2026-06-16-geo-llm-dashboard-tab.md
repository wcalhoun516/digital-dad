# Geo-LLM dashboard tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an insight-only `Geo-LLM` tab to the dashboard that auto-updates from real files: hero blurb, QLoRA explainer, live 26a–f pipeline tracker, dataset-at-a-glance, and a RAG-vs-fine-tune scoreboard.

**Architecture:** A pure-Python build-time generator (`analysis/geo_llm_status.py`) reads the training/eval artifacts and writes `data/analysis/geo_llm.json`. `viz/build_dashboard.py` invokes it and injects the JSON into a new `/*__GEO_LLM_DATA__*/` placeholder. `dashboard/template.html` gains a tab that renders the JSON client-side (no network calls). Mirrors `analysis/rag_eval.py` (pure helpers + thin IO) and the existing placeholder pattern.

**Tech Stack:** Python 3.12 (stdlib only: json, csv, pathlib), pytest, vanilla JS in `template.html`.

**Spec:** `docs/superpowers/specs/2026-06-16-geo-llm-dashboard-tab-design.md`

---

## File structure

- Create `analysis/geo_llm_status.py` — pure helpers (`dataset_stats`, `count_geo_tokens`, `pipeline_status`, `sample_pair`, `rag_summary`, `voice_summary`, `build_status`) + `write_status()` + `main()`.
- Create `tests/test_geo_llm_status.py` — offline unit tests on tmp fixtures.
- Modify `viz/build_dashboard.py` — register `/*__GEO_LLM_DATA__*/`, generate the file before injecting, add an empty default.
- Modify `dashboard/template.html` — tab button, `#tab-geollm` content shell, `GEO_LLM_DATA` const, render JS.

JSON shape (`data/analysis/geo_llm.json`):
```json
{
  "dataset": {"n_examples": 194, "n_train": 138, "n_heldout": 34, "n_columns": 196, "corpus_bytes": 2338447, "geo_tokens": 412345},
  "sample_pair": {"prompt": "...", "answer": "..."},
  "qlora": {"base_model": "Qwen2.5-3B", "frozen_pct": 98.5, "trainable_pct": 1.5},
  "pipeline": [{"id": "26a", "label": "Dataset builder", "status": "done"}, ...],
  "rag_baseline": {"grounding": 0.85, "citation_coverage": 0.60, "abstention_accuracy": 1.0},
  "voice_eval": null
}
```

---

## Task 1: Dataset stats + Geo Tokens (pure)

**Files:** Create `analysis/geo_llm_status.py`, `tests/test_geo_llm_status.py`

- [ ] **Step 1: Write failing tests**
```python
from pathlib import Path
import json, csv
from analysis import geo_llm_status as g

def _write_jsonl(p, n):
    p.write_text("\n".join(json.dumps({"messages": []}) for _ in range(n)) + "\n")

def test_count_geo_tokens_whitespace(tmp_path):
    f = tmp_path / "corpus.txt"
    f.write_text("the bond market tells a story")  # 6 words
    assert g.count_geo_tokens(f) == 6

def test_count_geo_tokens_missing_returns_zero(tmp_path):
    assert g.count_geo_tokens(tmp_path / "nope.txt") == 0

def test_dataset_stats(tmp_path):
    tdir = tmp_path / "training"; tdir.mkdir()
    _write_jsonl(tdir / "instruct.jsonl", 194)
    _write_jsonl(tdir / "train.jsonl", 138)
    _write_jsonl(tdir / "heldout.jsonl", 34)
    (tdir / "corpus.txt").write_text("a b c")
    with (tdir / "metadata.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["slug","title","date"]); w.writerow(["s","t","2020-01-01"]); w.writerow(["s2","t2","2021-01-01"])
    s = g.dataset_stats(tdir)
    assert s["n_examples"] == 194 and s["n_train"] == 138 and s["n_heldout"] == 34
    assert s["n_columns"] == 2 and s["geo_tokens"] == 3 and s["corpus_bytes"] == 5
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/test_geo_llm_status.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**
```python
"""Build-time status snapshot for the Geo-LLM dashboard tab (plan 0008 insight).

Pure file readers (offline, no conductor): assemble data/analysis/geo_llm.json from
the training artifacts + eval reports. Every field degrades to a safe default when its
source file is absent, so the dashboard build never breaks mid-experiment.
"""
import csv
import json
from pathlib import Path

from .utils import DATA_DIR

TRAINING_DIR = DATA_DIR / "training"
ANALYSIS_DIR = DATA_DIR / "analysis"
FINETUNE_RUN_DIR = DATA_DIR / "finetune_run"
REPORT_PATH = ANALYSIS_DIR / "geo_llm.json"


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open() as fh:
        return sum(1 for line in fh if line.strip())


def count_geo_tokens(corpus_path: Path) -> int:
    """Whitespace token count of the training corpus (0 if absent)."""
    if not corpus_path.exists():
        return 0
    return len(corpus_path.read_text().split())


def dataset_stats(training_dir: Path = TRAINING_DIR) -> dict:
    corpus = training_dir / "corpus.txt"
    meta = training_dir / "metadata.csv"
    n_columns = 0
    if meta.exists():
        with meta.open(newline="") as fh:
            n_columns = max(0, sum(1 for _ in csv.reader(fh)) - 1)  # minus header
    return {
        "n_examples": _count_lines(training_dir / "instruct.jsonl"),
        "n_train": _count_lines(training_dir / "train.jsonl"),
        "n_heldout": _count_lines(training_dir / "heldout.jsonl"),
        "n_columns": n_columns,
        "corpus_bytes": corpus.stat().st_size if corpus.exists() else 0,
        "geo_tokens": count_geo_tokens(corpus),
    }
```

- [ ] **Step 4: Run, verify pass** — same pytest command → PASS.

- [ ] **Step 5: Commit** — `git add analysis/geo_llm_status.py tests/test_geo_llm_status.py && git commit -m "geo-llm-tab: dataset stats + geo-token counter (pure)"`

---

## Task 2: Pipeline status + sample pair + eval summaries (pure)

**Files:** Modify `analysis/geo_llm_status.py`, `tests/test_geo_llm_status.py`

- [ ] **Step 1: Write failing tests**
```python
def test_sample_pair_extracts_user_and_assistant(tmp_path):
    f = tmp_path / "instruct.jsonl"
    rec = {"messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "What of the bond market?"},
        {"role": "assistant", "content": "The truth comes in layers..."}]}
    f.write_text(json.dumps(rec) + "\n")
    sp = g.sample_pair(f)
    assert sp["prompt"] == "What of the bond market?"
    assert sp["answer"].startswith("The truth")

def test_sample_pair_missing(tmp_path):
    assert g.sample_pair(tmp_path / "nope.jsonl") is None

def test_rag_summary_reads_summary_block(tmp_path):
    f = tmp_path / "rag_eval.json"
    f.write_text(json.dumps({"summary": {"grounding_rate": 0.85, "citation_coverage": 0.6, "abstention_accuracy": 1.0}}))
    assert g.rag_summary(f) == {"grounding": 0.85, "citation_coverage": 0.6, "abstention_accuracy": 1.0}

def test_rag_summary_missing(tmp_path):
    assert g.rag_summary(tmp_path / "nope.json") is None

def test_pipeline_status_marks_done_from_artifacts(tmp_path):
    # only the dataset + rag baseline exist → 26a, 26b done; rest not
    flags = {"dataset": True, "rag": True, "notebook": False, "voice_harness": False, "adapter": False, "voice_results": False}
    steps = g.pipeline_status(flags)
    by_id = {s["id"]: s["status"] for s in steps}
    assert by_id["26a"] == "done" and by_id["26b"] == "done"
    assert by_id["26c"] == "next"        # first not-done becomes "next"
    assert by_id["26d"] == "upcoming"
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement (append to `analysis/geo_llm_status.py`)**
```python
_PIPELINE = [
    ("26a", "Dataset builder", "dataset"),
    ("26b", "Baseline captured", "rag"),
    ("26c", "QLoRA fine-tune notebook", "notebook"),
    ("26d", "Voice-fidelity eval harness", "voice_harness"),
    ("26e", "Train adapter & register", "adapter"),
    ("26f", "Compare & decide", "voice_results"),
]


def sample_pair(instruct_path: Path) -> dict | None:
    if not instruct_path.exists():
        return None
    with instruct_path.open() as fh:
        first = fh.readline()
    if not first.strip():
        return None
    msgs = json.loads(first).get("messages", [])
    prompt = next((m["content"] for m in msgs if m.get("role") == "user"), None)
    answer = next((m["content"] for m in msgs if m.get("role") == "assistant"), None)
    if not prompt or not answer:
        return None
    return {"prompt": prompt, "answer": answer}


def _summary(path: Path, keymap: dict) -> dict | None:
    if not path.exists():
        return None
    summary = json.loads(path.read_text()).get("summary", {})
    return {out: summary.get(src) for out, src in keymap.items()}


def rag_summary(path: Path = ANALYSIS_DIR / "rag_eval.json") -> dict | None:
    return _summary(path, {"grounding": "grounding_rate",
                           "citation_coverage": "citation_coverage",
                           "abstention_accuracy": "abstention_accuracy"})


def voice_summary(path: Path = ANALYSIS_DIR / "voice_eval.json") -> dict | None:
    # Shape TBD by 26d output; surface whatever summary block exists, else None.
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("summary") or None


def pipeline_status(flags: dict) -> list[dict]:
    steps = []
    next_assigned = False
    for sid, label, flag in _PIPELINE:
        if flags.get(flag):
            status = "done"
        elif not next_assigned:
            status, next_assigned = "next", True
        else:
            status = "upcoming"
        steps.append({"id": sid, "label": label, "status": status})
    return steps
```
Note: `voice_summary` reads the real 26d `summary` block as-is; the template renders keys generically, so no coupling to exact metric names.

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit** — `git commit -am "geo-llm-tab: pipeline status, sample pair, eval summaries"`

---

## Task 3: Assemble + write geo_llm.json + CLI

**Files:** Modify `analysis/geo_llm_status.py`, `tests/test_geo_llm_status.py`

- [ ] **Step 1: Write failing test**
```python
def test_build_status_shape(tmp_path, monkeypatch):
    # point module dirs at tmp; only dataset present
    tdir = tmp_path / "training"; tdir.mkdir()
    _write_jsonl(tdir / "instruct.jsonl", 2); (tdir / "corpus.txt").write_text("a b")
    rec = {"messages": [{"role":"user","content":"q"},{"role":"assistant","content":"a"}]}
    (tdir / "instruct.jsonl").write_text(json.dumps(rec) + "\n" + json.dumps(rec) + "\n")
    adir = tmp_path / "analysis"; adir.mkdir()
    monkeypatch.setattr(g, "TRAINING_DIR", tdir)
    monkeypatch.setattr(g, "ANALYSIS_DIR", adir)
    monkeypatch.setattr(g, "FINETUNE_RUN_DIR", tmp_path / "none")
    status = g.build_status()
    assert set(status) == {"dataset", "sample_pair", "qlora", "pipeline", "rag_baseline", "voice_eval"}
    assert status["rag_baseline"] is None and status["voice_eval"] is None
    assert len(status["pipeline"]) == 6
    assert status["pipeline"][0]["status"] == "done"   # dataset present → 26a done
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement (append)**
```python
QLORA_DEFAULT = {"base_model": "Qwen2.5-3B", "frozen_pct": 98.5, "trainable_pct": 1.5}


def build_status() -> dict:
    ds = dataset_stats(TRAINING_DIR)
    rag = rag_summary(ANALYSIS_DIR / "rag_eval.json")
    voice = voice_summary(ANALYSIS_DIR / "voice_eval.json")
    flags = {
        "dataset": ds["n_examples"] > 0,
        "rag": rag is not None,
        "notebook": (FINETUNE_RUN_DIR / "train.jsonl").exists(),
        "voice_harness": (Path(__file__).with_name("voice_eval.py")).exists(),
        "adapter": False,            # set true once 26e registers an adapter
        "voice_results": voice is not None,
    }
    return {
        "dataset": ds,
        "sample_pair": sample_pair(TRAINING_DIR / "instruct.jsonl"),
        "qlora": QLORA_DEFAULT,
        "pipeline": pipeline_status(flags),
        "rag_baseline": rag,
        "voice_eval": voice,
    }


def write_status(path: Path = REPORT_PATH) -> dict:
    status = build_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    return status


def main(argv=None) -> int:
    status = write_status()
    print(f"Wrote {REPORT_PATH} — {status['dataset']['n_examples']} examples, "
          f"{sum(1 for s in status['pipeline'] if s['status']=='done')}/6 steps done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run full test file, verify pass.**

- [ ] **Step 5: Commit** — `git commit -am "geo-llm-tab: assemble + write geo_llm.json + CLI"`

---

## Task 4: Wire into the dashboard build

**Files:** Modify `viz/build_dashboard.py`

- [ ] **Step 1: Add the placeholder + empty default + generation call.**
In `PLACEHOLDERS` dict add: `"/*__GEO_LLM_DATA__*/": DATA_DIR / "analysis" / "geo_llm.json",`
In `_EMPTY_DEFAULTS` add: `"/*__GEO_LLM_DATA__*/": '{"dataset":null,"sample_pair":null,"qlora":null,"pipeline":[],"rag_baseline":null,"voice_eval":null}',`
At the top of `build()` (before reading placeholders), regenerate the file so a plain `make dashboard` is always fresh:
```python
    try:
        from analysis.geo_llm_status import write_status
        write_status()
    except Exception as exc:        # never let status-gen break the dashboard build
        print(f"  (geo_llm status skipped: {exc})")
```

- [ ] **Step 2: Build, verify it injects.**
Run: `.venv/bin/python viz/build_dashboard.py` → `Dashboard built: .../dashboard/index.html`
Run: `grep -c '"dataset"' dashboard/index.html` → ≥1 (real data injected, not the placeholder comment).

- [ ] **Step 3: Commit** — `git commit -am "geo-llm-tab: generate + inject geo_llm.json in build_dashboard"`

---

## Task 5: The tab (markup + data const + render JS)

**Files:** Modify `dashboard/template.html`

- [ ] **Step 1: Add the nav button** after the Track Record button (line ~650):
```html
  <button data-tab="geollm">Geo-LLM</button>
```

- [ ] **Step 2: Add the data const** next to the others (line ~838):
```javascript
const GEO_LLM_DATA = /*__GEO_LLM_DATA__*/;
```

- [ ] **Step 3: Add the tab-content shell** after the Track Record tab (line ~796 block end). A single `<div class="tab-content" id="tab-geollm">` with five empty section containers (`#geo-hero`, `#geo-qlora`, `#geo-pipeline`, `#geo-dataset`, `#geo-scoreboard`) the render fills. (Full markup written during execution, matching existing tab styling: section headers, `.metric`/card classes already in the stylesheet.)

- [ ] **Step 4: Add a render function** (plain JS, runs on load — no lazy hook needed since it's static):
```javascript
function renderGeoLLM() {
  const d = GEO_LLM_DATA; if (!d) return;
  // hero copy is static in markup; fill pipeline, dataset metrics, sample pair, scoreboard.
  // pipeline: map status -> {done: check/green, next: amber, upcoming: muted}.
  // dataset: n_examples, n_train/n_heldout, n_columns, corpus (MB), geo_tokens (toLocaleString).
  // scoreboard: rag_baseline as %; voice_eval -> render summary keys, else "awaiting first voice-eval".
}
renderGeoLLM();
```
Status→style and number formatting (`Math.round`, `toLocaleString`) per the visualize design rules; exact DOM-building written during execution.

- [ ] **Step 5: Build + smoke-check.**
Run: `make dashboard` → success. `grep -c 'data-tab="geollm"' dashboard/index.html` → 1.

- [ ] **Step 6: Commit** — `git commit -am "geo-llm-tab: add Geo-LLM tab markup + render"`

---

## Task 6: Verify end-to-end + degradation

- [ ] **Step 1:** `make verify` (lint + tests) → green; new tests included.
- [ ] **Step 2: Populated build** — with real `data/analysis/geo_llm.json`, run `make serve`, load `:8000`, open the Geo-LLM tab via preview tools; confirm all five sections render and the scoreboard shows RAG 85% / fine-tune "awaiting".
- [ ] **Step 3: Degradation build** — temporarily move `data/training` aside (or run in a tmp), rebuild, confirm the tab still renders with "—"/"in progress" and the build exits 0. Restore.
- [ ] **Step 4: Responsive** — `make verify-responsive` (roadmap #20 harness) passes with the tab present.
- [ ] **Step 5:** Open PR to `main`.

---

## Notes for the executor
- Stdlib only — do not add dependencies.
- `voice_eval.json`'s exact summary shape is owner-produced later (26d/26f); `voice_summary` surfaces its `summary` block generically, and the template renders whatever keys are present, so there is no hard coupling.
- Do not edit `roadmap.md`/`changelog.md` (human-curated) beyond, optionally, a one-line note.
- Leave the carried-over `data/manifest.json` working-tree change alone; it belongs to the daily agent, not this feature.
