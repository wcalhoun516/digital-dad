# Goals — the north star

## Why this exists

This is a son building an intellectual archive of his father, Dr. George Calhoun, from the
body of work he published as a Forbes columnist. The aim is not a website; it's a way to keep
a mind explorable — to be able to ask what he thought, see how his thinking moved over time,
and hand the family small artifacts that make him present.

## What "good" looks like

1. **Evidenced, not hallucinated.** When the system speaks in his voice (Ask Dad, On This
   Day intros), every claim is grounded in something he actually wrote and is citable back to
   the source article. An impression is worthless; an *evidenced* impression is the point.

2. **A living archive, not a museum.** The corpus should generate fresh things — a weekly
   email, an updated track record, new connections — so the family encounters it as
   something alive rather than a static page they visit once.

3. **Rigorous and auditable.** The analysis (themes, predictions, psychoprofile) should be
   honest enough that *he* would have respected it. Track Record in particular is a mirror for
   an intellectual style — it only works if it's fair. Verdicts are transparent and editable.

4. **Durable and low-maintenance.** It runs on a Mac mini, refreshes itself weekly, and
   improves itself daily (the product-dev agent). A family member should be able to open the
   dashboard years from now and have it still work.

5. **Respectful of the source.** Raw article text is gitignored (licensing); the value the
   project adds is analysis, structure, and access — not redistribution.

## Long-term directions

- **Depth of voice:** move from RAG toward an optional fine-tuned model, measured against a
  RAG baseline for faithfulness — never trading away groundedness for fluency.
- **Relational understanding:** beyond per-article analysis toward how ideas, people, and
  institutions connect and evolve across the whole corpus (entity graphs, stance-over-time,
  the "intellectual arc").
- **Family-facing surface:** make the artifacts effortless to receive — mobile-friendly,
  emailed, printable — so engagement doesn't require technical effort.
- **Self-improving:** the daily agent steadily pays down tech debt and builds out the roadmap
  so the project compounds without constant hands-on work.

The roadmap ([`roadmap.md`](roadmap.md)) is how these directions become concrete next steps.

---

## The longer-term goal: this is a product

**digital-dad is two things at once, and the second one is the bigger ambition.**

1. An archive of Dr. George Calhoun, built for his family.
2. The **reference implementation of a general product**: give it enough text by one person,
   and it produces a model that writes and reasons like them — grounded, citable, and
   evaluated rather than asserted. For a loved one who has died, for a parent while they're
   still here, or for yourself.

Dad is the vehicle, and a good one: the corpus is real, substantial, publicly licensed enough
to work with, and the owner knows the subject well enough to judge whether the output is
*actually him* — which is the only evaluation that finally matters and the hardest one to fake.

### What that implies for how we build

- **Assume a second subject.** Anything hard-coded to George Calhoun is future work to undo:
  prompt strings that name him, the distinctive-word list, the alias map, the RSS feed
  choices. Prefer configuration and per-subject data files over literals. This is not a
  mandate to generalize early — it is a reason to *notice* when you are hard-coding, and to
  leave the seam where it belongs.
- **The Forbes scraper is the least transferable part; the ingest registry is the most.**
  Most people do not have 200 published columns. They have email, documents, messages,
  photographs of letters, and recordings. The `(Path) -> ExtractResult` handler registry is
  the part of this codebase a second user would actually run, which is a reason to keep it
  pure, offline, and boring.
- **"Enough text" is an empirical question, and this project can answer it.** How much
  material does a person need before a fine-tune beats retrieval? Nobody knows. Every
  measured run here is a datapoint on that curve, and the curve is the product's core claim.
  Record corpus size alongside every eval result, not just the score.
- **Consent and privacy stop being theoretical.** A product means other people's parents,
  private letters, living subjects who did not choose this, and material whose author cannot
  be asked. The provenance model's `authorship` and `privacy` fields already anticipate it;
  the T3 private-document guard is the first enforcement. Treat that posture as load-bearing
  product design, not archive housekeeping.
- **Evaluation is the moat.** Anyone can fine-tune a model on a person and produce something
  fluent. The hard, valuable part is being able to say *how close it is, and where it is
  lying* — which is what `rag_eval`, `voice_eval` and the citation gate exist for. A
  competitor's demo is a vibe; this one has a scoreboard.

**This does not change the near-term order of work.** It changes what counts as done well: a
feature that only works because it knows it is about George Calhoun is a feature that will be
rewritten.
