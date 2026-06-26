"""Year in Review — an annual digest email from the archive.

Roadmap #23 (family): once a year, look back over everything Dr. Calhoun published in a
given calendar year and assemble a single keepsake email — how much he wrote, the themes
that dominated, and a handful of his most notable calls — in the same Georgia-serif voice
as the weekly "On This Day" note.

This module is deliberately **deterministic and offline**: it reads the analysis outputs
already on disk (`themes.json`, `predictions.json`) and the corpus, and renders an email to
``data/cron/emails/``. It makes no conductor, network, or LLM calls, so it is safe to run
unattended. Delivery stays human-in-the-loop via the existing Gmail-MCP draft path (D9).
"""
