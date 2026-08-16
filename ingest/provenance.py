"""Provenance vocabulary for corpus items (roadmap #29).

A corpus entry's ``provenance`` block records *what a thing is and how we got it*, so a
private letter and a published column are never mistaken for the same kind of evidence.

Named ``provenance``, not ``source``: ``data/raw/*.json`` already uses ``source`` for the
acquisition channel (``wayback`` / ``playwright``).
"""

from datetime import date as _date

MODALITIES = frozenset(
    {"article", "book", "course", "letter", "email", "message", "talk", "post"}
)
AUTHORSHIPS = frozenset({"george", "mixed", "other"})
PRIVACIES = frozenset({"public", "private"})
LICENSES = frozenset({"forbes", "owned", "purchased", "personal"})
DATE_CONFIDENCES = frozenset({"exact", "approximate", "unknown"})

_VOCABULARIES = {
    "modality": MODALITIES,
    "authorship": AUTHORSHIPS,
    "privacy": PRIVACIES,
    "license": LICENSES,
    "date_confidence": DATE_CONFIDENCES,
}


def default_provenance(**overrides) -> dict:
    """Build a provenance block, private-by-default, validating every vocabulary field.

    Defaults are the safe reading of an unknown item: it is his writing, it is private,
    and we do not trust its date until a human says otherwise.
    """
    prov = {
        "source_id": "",
        "modality": "article",
        "authorship": "george",
        "privacy": "private",
        "license": "personal",
        "acquisition": {"method": "ingest", "ref": "", "at": _date.today().isoformat()},
        "date_confidence": "unknown",
    }
    for key, value in overrides.items():
        if key not in prov:
            raise ValueError(f"unknown provenance field: {key!r}")
        vocabulary = _VOCABULARIES.get(key)
        if vocabulary is not None and value not in vocabulary:
            raise ValueError(
                f"invalid {key}: {value!r} — expected one of {sorted(vocabulary)}"
            )
        prov[key] = value
    return prov


def migrate_articles(articles: list[dict]) -> tuple[list[dict], int]:
    """Add a ``provenance`` block to scraped Forbes articles that lack one.

    Pure and offline: takes and returns article dicts, never touches disk. Idempotent —
    entries that already carry ``provenance`` pass through untouched. Returns
    ``(articles, migrated_count)``.
    """
    migrated = 0
    out: list[dict] = []
    for entry in articles:
        if not entry.get("provenance"):
            entry = {
                **entry,
                "provenance": default_provenance(
                    source_id=entry.get("slug", ""),
                    modality="article",
                    authorship="george",
                    privacy="public",
                    license="forbes",
                    acquisition={
                        "method": "scrape",
                        "ref": entry.get("url", ""),
                        "at": entry.get("date", ""),
                    },
                    date_confidence="exact",
                ),
            }
            migrated += 1
        out.append(entry)
    return out, migrated
