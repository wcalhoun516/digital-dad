# Plan 0005 — Ask Dad polish (persistence + citation deep-links)

## Goal

Make the Ask Dad chat feel like a real, keepable conversation: (a) persist chat history so a
refresh doesn't wipe it, with a transcript export, and (b) make each cited source clickable —
deep-linking into the Raw Corpus tab and highlighting the matched passage. Deepen (§8.5) from
persistence (#18) into the deep-links (#19).

## Context

- All client-side per **decision D4** — vanilla JS + D3, **no framework, no build step**.
  Work in `dashboard/template.html`; rebuild with `make dashboard` (`viz/build_dashboard.py`
  injects data into the template → `dashboard/index.html`).
- Ask Dad already: expands the query (T1), embeds (sbert), retrieves top-8 by cosine, streams
  a conductor chat completion, and renders sources. Retrieval uses `EMBEDDINGS_DATA` (with
  per-article `snippets`) baked into the page. Citations already list article titles.
- The Raw Corpus tab already renders the full article list and is searchable/sortable — the
  deep-link target.

## Steps

1. **Persistence:** store chat turns in `localStorage` (versioned key); restore on load; add a
   "Clear" button and an "Export transcript" action (download `.md`/`.txt` with Q/A + sources).
   Keep it resilient to the data schema changing (guard on version).
2. **Citation deep-links:** make each source citation a link that switches to the Raw Corpus
   tab, scrolls to / filters that article, and highlights the matched snippet text. Reuse the
   existing tab-switch + corpus-render functions rather than duplicating them.
3. Keep the persona/system-prompt construction and retrieval logic unchanged — this is UX
   polish, not a retrieval change.

## Verification

- `make dashboard`, then use the preview tools: ask a question, reload, confirm history
  restored; click a citation, confirm it lands on the right article in Raw Corpus with the
  passage highlighted; export and open the transcript.
- Check `preview_console_logs` for errors after each interaction.
- `superpowers:verification-before-completion` with a screenshot before flipping ready.

## Out of scope

- Server-side history, multi-user accounts, rate limiting / cost warnings (separate items),
  mobile layout (that's 0006).
