"""What the corpus is made of (roadmap #38's open dashboard remainder).

The product's standing question is *how much text is enough* — D19/D20 measured three LoRA
runs at ~453K tokens and every one was token-starved, so roadmap #62 says spend the next run
on tokens, not hyperparameters. Nothing in the repo answered "what is the corpus made of?",
so there was no dial for the one variable that matters.

Two judgements are pinned here, both of which a naive item-count breakdown gets wrong.

**Words, not items, is the unit.** Roadmap #35: one ebook is ~80k words, roughly the entire
current corpus. A panel counting items would read "204 articles, 1 book" and hide that the
book is a third of the tokens.

**The manifest is the record, not `load_articles()`.** An accepted ingest item gets a
manifest entry with no ``file`` key, and ``load_articles`` skips those, so tallying loaded
articles would report zero books forever — the dial would lie on exactly the axis it exists
to measure. The words the pipeline cannot yet read are counted and reported *separately*
rather than dropped.
"""

from analysis.corpus_composition import compose

# No provenance block: every entry in today's real manifest looks like this, because roadmap
# #29's one-time data migration is still pending.
LEGACY_COLUMN = {
    "slug": "europes-hamiltonian-moment",
    "title": "Europe's Hamiltonian Moment",
    "date": "2020-05-26",
    "word_count": 1804,
    "file": "raw/europes-hamiltonian-moment.json",
}
SECOND_COLUMN = {
    "slug": "the-ecb-blinks",
    "title": "The ECB Blinks",
    "date": "2021-03-01",
    "word_count": 1200,
    "file": "raw/the-ecb-blinks.json",
}
# An accepted ingest item: carries provenance, and carries no `file`.
INGESTED_BOOK = {
    "slug": "book-9f8e7d6c",
    "title": "Price and Value",
    "word_count": 80000,
    "provenance": {
        "source_id": "book-9f8e7d6c",
        "modality": "book",
        "authorship": "george",
        "privacy": "private",
    },
}
INGESTED_THREAD = {
    "slug": "thread-1a2b3c4d",
    "title": "Re: the Fed's next move",
    "word_count": 900,
    "provenance": {
        "source_id": "thread-1a2b3c4d",
        "modality": "email",
        "authorship": "mixed",
        "privacy": "private",
    },
}


def _manifest(*entries):
    return {"articles": list(entries)}


def _by_name(rows):
    return {row["name"]: row for row in rows}


class TestModalityBreakdown:
    def test_a_legacy_column_counts_as_an_article_without_its_own_provenance(self):
        """Resolved through the same helper the T3 guard uses, not a second guess about
        what an un-migrated entry is."""
        result = compose(_manifest(LEGACY_COLUMN), readable_slugs={LEGACY_COLUMN["slug"]})
        rows = _by_name(result["by_modality"])
        assert set(rows) == {"article"}
        assert rows["article"]["items"] == 1
        assert rows["article"]["words"] == 1804

    def test_an_ingested_book_is_counted_under_its_own_modality(self):
        result = compose(
            _manifest(LEGACY_COLUMN, INGESTED_BOOK),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        rows = _by_name(result["by_modality"])
        assert rows["book"]["items"] == 1
        assert rows["book"]["words"] == 80000

    def test_one_book_outweighs_many_columns_in_words_while_losing_on_items(self):
        """The whole reason the unit is words. An item count would call this corpus
        overwhelmingly articles; in the tokens a model actually reads, it is mostly book."""
        result = compose(
            _manifest(LEGACY_COLUMN, SECOND_COLUMN, INGESTED_BOOK),
            readable_slugs={LEGACY_COLUMN["slug"], SECOND_COLUMN["slug"]},
        )
        rows = _by_name(result["by_modality"])
        assert rows["article"]["items"] > rows["book"]["items"]
        assert rows["book"]["words"] > rows["article"]["words"]

    def test_rows_are_ordered_by_words_so_the_panel_is_deterministic(self):
        result = compose(
            _manifest(LEGACY_COLUMN, SECOND_COLUMN, INGESTED_BOOK, INGESTED_THREAD),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        words = [row["words"] for row in result["by_modality"]]
        assert words == sorted(words, reverse=True)

    def test_share_is_measured_in_words_not_items(self):
        result = compose(
            _manifest(LEGACY_COLUMN, INGESTED_BOOK),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        rows = _by_name(result["by_modality"])
        assert rows["book"]["share"] > 0.9
        assert abs(sum(row["share"] for row in result["by_modality"]) - 1.0) < 1e-9


class TestAuthorshipBreakdown:
    def test_a_mixed_thread_is_not_counted_as_his_writing(self):
        """An email thread carries other people's replies. Training a voice model on it
        teaches the wrong voice, so the panel has to separate it."""
        result = compose(
            _manifest(LEGACY_COLUMN, INGESTED_THREAD),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        rows = _by_name(result["by_authorship"])
        assert rows["george"]["words"] == 1804
        assert rows["mixed"]["words"] == 900

    def test_a_legacy_column_reads_as_his(self):
        result = compose(_manifest(LEGACY_COLUMN), readable_slugs={LEGACY_COLUMN["slug"]})
        assert _by_name(result["by_authorship"])["george"]["items"] == 1


class TestWhatThePipelineCanActuallyRead:
    def test_an_entry_with_no_raw_file_is_counted_as_unreadable(self):
        """`accept_item` writes a manifest entry with no `file`, and `load_articles` skips
        those. Those words are in the corpus record but reach no analysis module."""
        result = compose(
            _manifest(LEGACY_COLUMN, INGESTED_BOOK),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        assert result["readable"]["items"] == 1
        assert result["readable"]["words"] == 1804
        assert result["unreadable"]["items"] == 1
        assert result["unreadable"]["words"] == 80000

    def test_unreadable_words_are_still_counted_in_the_total(self):
        """They are part of the corpus the owner has accepted; hiding them would
        under-report what has been gathered."""
        result = compose(
            _manifest(LEGACY_COLUMN, INGESTED_BOOK),
            readable_slugs={LEGACY_COLUMN["slug"]},
        )
        assert result["total"]["items"] == 2
        assert result["total"]["words"] == 81804

    def test_a_fully_readable_corpus_reports_nothing_unreadable(self):
        result = compose(
            _manifest(LEGACY_COLUMN, SECOND_COLUMN),
            readable_slugs={LEGACY_COLUMN["slug"], SECOND_COLUMN["slug"]},
        )
        assert result["unreadable"] == {"items": 0, "words": 0}


class TestTheHttpsTwins:
    """The scraper historically upserted on URL, so 23 of today's 204 manifest entries are
    http/https twins naming the *same* raw file. `load_articles` dedupes them; a panel that
    did not would over-report the corpus by 23 items and 37,728 words — 11% — which is the
    wrong direction to be wrong about "how much text is enough"."""

    def test_two_entries_naming_the_same_raw_file_count_once(self):
        twin = {**LEGACY_COLUMN, "slug": "europes-hamiltonian-moment-2"}
        result = compose(
            _manifest(LEGACY_COLUMN, twin), readable_slugs={LEGACY_COLUMN["slug"]}
        )
        assert result["total"]["items"] == 1
        assert result["total"]["words"] == 1804

    def test_two_ingested_entries_with_no_raw_file_are_both_kept(self):
        """They share the empty `file` field but are genuinely different documents."""
        result = compose(_manifest(INGESTED_BOOK, INGESTED_THREAD), readable_slugs=set())
        assert result["total"]["items"] == 2


class TestEdges:
    def test_an_empty_manifest_does_not_divide_by_zero(self):
        result = compose(_manifest(), readable_slugs=set())
        assert result["total"] == {"items": 0, "words": 0}
        assert result["by_modality"] == []
        assert result["by_authorship"] == []

    def test_an_entry_with_no_word_count_contributes_no_words_but_still_counts(self):
        """A manifest entry is a thing the owner accepted even if nobody measured it."""
        result = compose(
            _manifest({"slug": "mystery", "file": "raw/mystery.json"}),
            readable_slugs={"mystery"},
        )
        assert result["total"] == {"items": 1, "words": 0}
        assert _by_name(result["by_modality"])["article"]["items"] == 1
