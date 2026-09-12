"""Resolving manifest entries to provenance blocks for the T3 guard (roadmap #38).

The callers that make paid remote calls hold slugs and article dicts, not provenance. This
is the lookup between them. It has to cope with the fact that **no manifest entry carries a
provenance block today** — roadmap #29 landed the schema but its one-time data migration is
still pending — without reading all 204 scraped Forbes columns as private and thereby
refusing every paid call the owner makes.
"""

import pytest

from analysis.conductor import PrivateContentError, assert_remote_allowed
from analysis.utils import corpus_provenance, provenance_for_slugs

LEGACY = {
    "slug": "europes-hamiltonian-moment",
    "title": "Europe's Hamiltonian Moment",
    "date": "2020-05-26",
    "url": "http://www.forbes.com/sites/georgecalhoun/2020/05/26/europes-hamiltonian-moment/",
    "file": "raw/europes-hamiltonian-moment.json",
}
INGESTED_PRIVATE = {
    "slug": "a-letter",
    "title": "Letter to the board",
    "provenance": {"source_id": "a-letter", "modality": "letter", "privacy": "private"},
}
MANIFEST = {"articles": [LEGACY, INGESTED_PRIVATE]}


class TestProvenanceForSlugs:
    def test_a_legacy_scraped_column_reads_as_public(self):
        """Every entry in today's manifest is a published Forbes column."""
        (prov,) = provenance_for_slugs(["europes-hamiltonian-moment"], manifest=MANIFEST)
        assert prov["privacy"] == "public"
        assert prov["modality"] == "article"

    def test_an_ingested_private_entry_keeps_its_own_provenance(self):
        (prov,) = provenance_for_slugs(["a-letter"], manifest=MANIFEST)
        assert prov["privacy"] == "private"

    def test_an_unknown_slug_is_not_silently_dropped(self):
        """Dropping it would let unidentifiable text ride along to OpenRouter."""
        (prov,) = provenance_for_slugs(["never-heard-of-it"], manifest=MANIFEST)
        assert prov.get("privacy") != "public"
        assert prov["source_id"] == "never-heard-of-it"

    def test_returns_one_block_per_requested_slug(self):
        blocks = provenance_for_slugs(["a-letter", "europes-hamiltonian-moment"], manifest=MANIFEST)
        assert [b["source_id"] for b in blocks] == ["a-letter", "europes-hamiltonian-moment"]

    def test_a_repeated_slug_is_asked_about_once(self):
        blocks = provenance_for_slugs(["a-letter", "a-letter"], manifest=MANIFEST)
        assert len(blocks) == 1


class TestCorpusProvenance:
    def test_covers_every_manifest_entry(self):
        blocks = corpus_provenance(manifest=MANIFEST)
        assert {b["source_id"] for b in blocks} == {"europes-hamiltonian-moment", "a-letter"}

    def test_one_private_document_makes_the_whole_corpus_unsendable(self):
        """What ``voice_eval`` needs: its trial passages could come from any article."""
        with pytest.raises(PrivateContentError):
            assert_remote_allowed(corpus_provenance(manifest=MANIFEST))

    def test_a_wholly_public_corpus_is_sendable(self):
        assert_remote_allowed(corpus_provenance(manifest={"articles": [LEGACY]})) is None
