"""corpus_composition: what the corpus is made of, measured in words.

Roadmap #38's open dashboard remainder. The product's standing question is *how much text is
enough* — roadmap #62 keeps the LoRA track open precisely because every run so far was
token-starved — and nothing in the repo answered the prior question of what the corpus is
actually made of. This is that dial.

Three things here are deliberate, because the obvious version of each is wrong.

**Words, not items.** One ebook is ~80k words, roughly the whole current corpus (roadmap #35).
An item count would read "204 articles, 1 book" and hide that the book is a third of the
tokens a model reads. Items are reported too, but shares are computed on words.

**The manifest is the corpus record — not ``load_articles()``.** ``ingest.review.accept_item``
appends a manifest entry with no ``file`` key, and ``load_articles`` skips those, so a tally
built from loaded articles would report zero books forever. What the pipeline cannot yet read
is counted and reported *separately* rather than dropped, so the gap is visible instead of
silent.

**Entries are deduped the same way the loader dedupes them.** 23 of today's 204 entries are
http/https twins naming the same raw file; counting them would over-report the corpus by 11%.
"""

from .utils import dedupe_manifest_entries, load_articles, load_manifest, log, save_analysis


def _tally(rows: list[tuple[str, int]]) -> list[dict]:
    """Group ``(name, words)`` pairs into word-ordered rows with their share of the total."""
    totals: dict[str, dict] = {}
    for name, words in rows:
        bucket = totals.setdefault(name, {"name": name, "items": 0, "words": 0})
        bucket["items"] += 1
        bucket["words"] += words

    total_words = sum(bucket["words"] for bucket in totals.values())
    for bucket in totals.values():
        bucket["share"] = (bucket["words"] / total_words) if total_words else 0.0
    # Words descending, then name, so the panel's bar order never depends on dict ordering.
    return sorted(totals.values(), key=lambda b: (-b["words"], b["name"]))


def compose(manifest: dict, readable_slugs) -> dict:
    """Break the corpus down by modality and authorship.

    ``readable_slugs`` is the set of slugs the analysis pipeline can actually load. It is
    required rather than defaulted because the interesting number — material accepted into
    the corpus that no module can read yet — is exactly the difference between the two, and a
    default would quietly report it as zero.
    """
    from ingest.provenance import migrate_articles

    entries = dedupe_manifest_entries(manifest.get("articles", []))
    # The same resolution the T3 guard uses, so an un-migrated Forbes column is described
    # once in the repo rather than guessed at twice.
    resolved, _ = migrate_articles(entries)

    readable = {"items": 0, "words": 0}
    unreadable = {"items": 0, "words": 0}
    modalities: list[tuple[str, int]] = []
    authorships: list[tuple[str, int]] = []

    for entry in resolved:
        provenance = entry.get("provenance") or {}
        words = entry.get("word_count") or 0
        modalities.append((provenance.get("modality") or "unknown", words))
        authorships.append((provenance.get("authorship") or "unknown", words))

        bucket = readable if entry.get("slug", "") in readable_slugs else unreadable
        bucket["items"] += 1
        bucket["words"] += words

    return {
        "total": {
            "items": readable["items"] + unreadable["items"],
            "words": readable["words"] + unreadable["words"],
        },
        "readable": readable,
        "unreadable": unreadable,
        "by_modality": _tally(modalities),
        "by_authorship": _tally(authorships),
    }


def run(articles: list[dict] | None = None) -> dict:
    if articles is None:
        articles = load_articles()

    result = compose(load_manifest(), {article.get("slug", "") for article in articles})

    log.info(
        "Corpus: %d items, %d words across %d modalities",
        result["total"]["items"],
        result["total"]["words"],
        len(result["by_modality"]),
    )
    if result["unreadable"]["items"]:
        log.warning(
            "%d accepted item(s) (%d words) have no readable raw file — accepted into the "
            "manifest but reaching no analysis module",
            result["unreadable"]["items"],
            result["unreadable"]["words"],
        )

    path = save_analysis("corpus_composition.json", result)
    log.info("corpus_composition saved to %s", path)
    return result


if __name__ == "__main__":
    run()
