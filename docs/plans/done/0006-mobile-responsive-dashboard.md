# Plan 0006 — Mobile-responsive dashboard

## Goal

The family will open this on phones. Make the dashboard usable on small screens: tabs,
charts, the Raw Corpus table, Ask Dad, and Track Record should all be legible and operable
at ~375px wide without horizontal scrolling or broken layouts.

## Context

- Client-side only per **decision D4** — vanilla CSS/JS + D3, **no framework, no build step**.
  Edit `dashboard/template.html`; rebuild via `make dashboard`.
- The hard cases are the D3 visualizations (force-directed theme map, radar, scatter
  timeline) and the wide Raw Corpus / Track Record tables. D3 charts need responsive
  sizing (viewBox / width-from-container) rather than fixed pixel dimensions.
- The tab navigation itself likely needs a mobile treatment (scrollable/stacked).

## Steps

1. Add a responsive CSS layer (media queries; fluid containers; readable base font on mobile).
   Make the tab bar work on narrow screens (horizontal scroll or a select/stack).
2. Make each D3 chart size to its container and re-render on resize/orientation change. Start
   with the most-used tabs (Theme Map, Timeline, Ask Dad), then the tables.
3. Make wide tables (Raw Corpus, Track Record) scroll or reflow into cards on mobile.
4. Don't regress desktop — verify both breakpoints.

## Verification

- `make dashboard`, then `preview_resize` to phone widths (e.g. 375×812) and desktop; take
  `preview_screenshot` at both. Exercise tab switches + a chart + a table at mobile width.
- `preview_console_logs` clean after resizes.
- `superpowers:verification-before-completion` with before/after mobile screenshots.

## Out of scope

- A separate native app, PWA/offline, or a full visual redesign — this is responsiveness, not
  restyling.

## Status — done (2026-06-10)

- **Step 1** (responsive CSS layer + scrollable tab bar) shipped in PR #9 (2026-06-07).
- **Step 2** (D3 charts re-render on resize/orientation, debounced) shipped in PR #13 (2026-06-08).
- **Step 3** (Raw Corpus table reflows into labelled cards at ≤480px) shipped in PR #14 (2026-06-09).
- **Step 4** (don't regress desktop; verify both breakpoints) shipped in PR #15 (2026-06-10).
  Prior steps each flagged "live phone-width browser pass not run (no preview tooling)";
  Playwright + Chromium are in fact available in `.venv`, so this step added
  `viz/verify_responsive.py` (run via `make verify-responsive`) — a headless-browser harness
  that renders the *built* `dashboard/index.html` at desktop (1280×900) and phone (375×812),
  asserting no horizontal overflow, a clean JS console, the corpus table staying a real table
  on desktop while reflowing to cards on a phone, and the step-2 resize-redraw surviving a
  live desktop→phone transition. **10/10 checks passed**; screenshots confirm the card reflow.
  Kept out of `make verify` because CI has no browser (the script SKIPs cleanly when Chromium
  is absent).
