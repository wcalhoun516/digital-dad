# Plan 0004 — Track Record fully alive (verdict backfill + adjudication)

## Goal

Turn the Track Record from "every prediction pending" into a real scoreboard. Two parts:
(a) a web-search-augmented pass that proposes a verdict for each falsifiable prediction, and
(b) a tiny adjudication CLI so the family can confirm/override verdicts by hand. Deepen
(§8.5) into confidence calibration (roadmap #12) once the core lands. This is the
emotionally resonant piece — a fair audit of how his bets actually turned out.

## Context

- Reuse `analysis/predictions.py`: predictions are already extracted into
  `data/analysis/predictions.json` with `{claim, target_date_or_horizon, confidence_language,
  topic, status, llm_verdict, ...}`. The `_run_verdicts()` pass already does a non-augmented
  LLM verdict; this plan adds an evidence-augmented option and a human override layer.
- LLM access is via the conductor (T2 local / T3 remote); web-search augmentation likely
  needs T3 or an external search step — check what the conductor exposes before assuming.
- Dashboard "Track Record" tab reads `predictions.json` and already renders status pills +
  aggregates; new fields must stay backward-compatible with its parser
  (`dashboard/template.html`).
- **Do not commit** the regenerated `predictions.json` as a giant blob churn — keep diffs
  reviewable; the file is tracked, so commit deliberate updates only.

## Steps

1. **Verdict backfill:** extend the verdict pass with an evidence-augmented mode — for each
   prediction, gather context (web search or supplied evidence) and have a T3 model return
   `{verdict, reasoning, confidence, sources}`. Make it resumable + incremental like the
   existing extraction (saves every N).
2. **Adjudication CLI:** a small `python -m analysis.adjudicate` (or `bin/` script) that walks
   unadjudicated predictions, shows claim + LLM verdict + sources, and lets a human set a
   `human_verdict` + note, writing back into `predictions.json`. Human verdict wins over LLM.
3. **Status precedence:** define how `status` is computed (human > llm > pending) and surface
   `verdict_source` in the JSON so the dashboard can show who decided.
4. **Deepen → calibration (#12):** aggregate hit-rate by `confidence_language`
   (hedged/confident/certain), "most right / most wrong" lists, and add them to the tab.

## Verification

- TDD the status-precedence + adjudication-writeback logic on a fixture predictions file.
- Run the backfill on a small slice (a handful of predictions), eyeball the verdicts + sources.
- `make dashboard` smoke build; confirm the Track Record tab still parses and shows verdicts.
- `superpowers:verification-before-completion` before flipping ready.

## Out of scope

- Comparing his hit-rate to other columnists; automated truth-checking without any human
  review (the family adjudication step is the point).
