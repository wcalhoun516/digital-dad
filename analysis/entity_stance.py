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

# Transparent polarity lexicon. Tone words common in his financial/political commentary; a
# sentence's polarity is (positive hits − negative hits), so the choice is deliberately small
# and legible rather than exhaustive. Matched on lowercased word tokens (see `_TOKEN_RE`).
_POSITIVE = frozenset({
    "success", "successful", "succeed", "strong", "strength", "gain", "gains", "gained",
    "win", "wins", "won", "growth", "grow", "growing", "boom", "booming", "innovative",
    "innovation", "brilliant", "resilient", "robust", "opportunity", "promising", "impressive",
    "sound", "healthy", "confidence", "confident", "triumph", "achievement", "prudent", "wise",
    "credible", "stable", "stability", "recovery", "thrive", "thrives", "thriving", "praise",
    "remarkable", "outstanding", "effective", "efficient", "breakthrough", "vindicated",
})
_NEGATIVE = frozenset({
    "failure", "fail", "fails", "failed", "failing", "weak", "weakness", "loss", "losses",
    "lose", "losing", "crisis", "collapse", "disaster", "disastrous", "risk", "risky",
    "danger", "dangerous", "threat", "threaten", "fraud", "fraudulent", "corruption", "corrupt",
    "reckless", "bubble", "crash", "decline", "declining", "worst", "damage", "flawed",
    "flaw", "dubious", "trouble", "troubled", "mistake", "misguided", "illusion", "problematic",
    "unsustainable", "doomed", "panic", "fear", "fears", "scandal", "chaos", "broken",
    "stagnant", "stagnation", "overvalued", "delusion", "folly", "hubris",
})
# A polarity hit is flipped when one of these appears within the preceding `_NEG_WINDOW` tokens.
_NEGATORS = frozenset({"not", "no", "never", "without", "hardly", "barely", "nor", "n't", "cannot"})
_NEG_WINDOW = 3

_TOKEN_RE = re.compile(r"[a-z][a-z']*")


def sentence_polarity(sentence: str) -> int:
    """Signed tone of one sentence via the transparent polarity lexicon.

    Returns ``(#positive − #negative)`` over the sentence's word tokens, where a polarity word
    is **flipped** if a negator (:data:`_NEGATORS`) occurs within the preceding
    :data:`_NEG_WINDOW` tokens. Case-insensitive; no model, no network. 0 means neutral (or a
    balance of positive and negative cues).
    """
    tokens = _TOKEN_RE.findall(sentence.lower())
    score = 0
    for i, tok in enumerate(tokens):
        if tok in _POSITIVE:
            sign = 1
        elif tok in _NEGATIVE:
            sign = -1
        else:
            continue
        window = tokens[max(0, i - _NEG_WINDOW):i]
        if any(w in _NEGATORS for w in window):
            sign = -sign
        score += sign
    return score
