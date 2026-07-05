"""Reading Room — a clean, paginated full-article reader for the family dashboard.

Roadmap #21 (dashboard / family-facing): assemble the corpus into an ordered,
navigable reading experience — every column with its full body, theme tag, prev/next
links, and a "read on Forbes" deep link — so the family can sit and *read* the archive,
not just query or chart it.

Deterministic and offline: joins the metadata already on disk (``themes.json`` for the
per-article theme label, the manifest for ordering/word counts) with the full article
bodies from ``data/raw/*.json``. Makes no conductor/network/LLM calls, so it is safe to
run unattended.

Licensing: the emitted ``reading_room.json`` embeds full article bodies, so — like
``embeddings.json`` and ``anthology.json`` — it is **git-ignored** and regenerated on
demand (``make reading-room``). Full text lives only in the owner's local build (and the
git-ignored ``dashboard/index.html``); it is never committed and never present in CI,
where the dashboard inlines an empty stub instead.
"""

from .utils import ANALYSIS_DIR

THEMES_PATH = ANALYSIS_DIR / "themes.json"
OUT_DIR = ANALYSIS_DIR
