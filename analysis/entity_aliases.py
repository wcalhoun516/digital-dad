"""Entity surface-form canonicalization (roadmap #14, alias-merge slice).

The spaCy extractor emits many spellings for the same subject — ``the Federal Reserve``,
``The Federal Reserve``, ``Federal Reserve`` and ``Fed`` are four separate strings for one
institution — so downstream builders split a single subject across several nodes. This module
is the one, transparent place that collapses those variants onto a canonical display name.

Two rules, applied in order (both pure/offline, stdlib only):

1. **Strip a single leading "the"** (case-insensitive) — safe for org names like
   ``the New York Stock Exchange`` while leaving mid-name "the" (``Bank of the West``) alone.
2. **Curated alias map** (:data:`ALIASES`, lowercased keys) — a small, corpus-specific,
   owner-editable table of known synonyms for Dr. Calhoun's finance beat. Anything not in the
   map passes through with only whitespace normalized and its original casing preserved.

The map is deliberately conservative and hand-checked against the committed ``entity_graph.json``
(``Powell`` → ``Jerome Powell`` and ``Ma`` → ``Jack Ma`` are corpus-specific: in this archive
those surnames are unambiguous). Extend or trim it in one place; every consumer picks up the
change on its next (offline) rebuild.
"""

import re

# Lowercased source spelling -> canonical display name. Applied *after* the leading-"the" strip,
# so e.g. "The Federal Reserve" -> "Federal Reserve" -> "Federal Reserve" (identity here) and
# "the Fed" -> "Fed" -> "Federal Reserve". Every canonical value must itself be a fixed point
# (canonicalize(value) == value) — see test_alias_map_hygiene.
ALIASES: dict[str, str] = {
    # The Fed
    "fed": "Federal Reserve",
    "federal reserve": "Federal Reserve",
    # Treasury (spaCy emits the plural "Treasurys" for Treasury securities/the department)
    "treasury": "Treasury",
    "treasurys": "Treasury",
    # Covid casing / hyphenation
    "covid": "Covid",
    "covid-19": "Covid",
    "covid19": "Covid",
    # Fed chair — surname is unambiguous in this corpus
    "powell": "Jerome Powell",
    "jerome powell": "Jerome Powell",
    # Alibaba/Ant founder — surname is unambiguous in this corpus
    "ma": "Jack Ma",
    "jack ma": "Jack Ma",
    # Bureau of Labor Statistics (the CPI/jobs source he cites constantly)
    "bls": "Bureau of Labor Statistics",
    "bureau of labor statistics": "Bureau of Labor Statistics",
    # European Central Bank
    "ecb": "European Central Bank",
    "european central bank": "European Central Bank",
}

_LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)
# Trailing possessive: straight or curly apostrophe + optional s. The extractor's own
# normalizer only strips the *straight* "'s", so "Federal Reserve’s" (curly) leaks through as a
# separate entity; catch both here.
_POSSESSIVE = re.compile(r"[’']s?$")


def _strip_leading_the(name: str) -> str:
    """Drop a single leading "the " (case-insensitive), unless it would empty the name."""
    stripped = _LEADING_THE.sub("", name, count=1)
    return stripped if stripped else name


def _strip_possessive(name: str) -> str:
    """Drop a trailing possessive (``'s`` / ``’s`` / apostrophe), unless it empties the name."""
    stripped = _POSSESSIVE.sub("", name).strip()
    return stripped if stripped else name


def canonicalize(name: str) -> str:
    """Map an extracted entity surface form onto its canonical display name.

    Whitespace-normalizes, strips a trailing possessive and a leading "the", then applies the
    curated :data:`ALIASES` table (case-insensitive). Unknown names pass through with original
    casing preserved. Blank input returns ``""``.
    """
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return ""
    name = _strip_possessive(name)
    name = _strip_leading_the(name).strip()
    return ALIASES.get(name.lower(), name)
