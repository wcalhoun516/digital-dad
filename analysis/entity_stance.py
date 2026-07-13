"""Per-entity stance over time — how his tone toward a person/org shifts by year (roadmap #17).

Reads the entity extraction already on disk (`data/analysis/entities.json`) plus the corpus
bodies, and for each major entity tracks a **stance trajectory**: the mean tone of the sentences
that mention it, aggregated per year. It's a companion to `entity_graph.py` (#14) — this module
ships the deterministic builder; a dashboard "stance over time" viz is a later slice.

Deliberately **deterministic and offline**: no conductor, network, or LLM calls, so it is safe
to run unattended. The nltk/VADER path used elsewhere is unavailable in this environment, so
stance here is a **transparent heuristic**: a small, hand-curated polarity lexicon scores each
sentence (positive terms minus negative terms, with a light negation flip), and an entity's
stance in an article is the mean polarity of the sentences that name it. This is a proxy for
tone, not a claim of ground-truth sentiment — it is meant to surface *trends*, not verdicts.

The output (`entity_stance.json`) carries only public entity names, numeric stance scores,
counts, and years — **no article-body text** — so it is committable exactly like
`entity_graph.json` (contrast `calhoun_isms.json`, which embeds sentences and is gitignored).
"""

import argparse
import re

from .entity_graph import _DEFAULT_EXCLUDE, _norm_exclude, article_entities, entity_id
from .utils import ANALYSIS_DIR, clean_text, load_articles, save_analysis
