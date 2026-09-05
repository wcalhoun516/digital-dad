"""Tests for ingest/provenance.py — the provenance vocabulary and defaults."""

import pytest

from ingest.provenance import (
    AUTHORSHIPS,
    MODALITIES,
    default_provenance,
    migrate_articles,
)


class TestDefaultProvenance:
    def test_defaults_are_private_and_george(self):
        prov = default_provenance()
        assert prov["authorship"] == "george"
        assert prov["privacy"] == "private"
        assert prov["date_confidence"] == "unknown"

    def test_every_required_key_is_present(self):
        prov = default_provenance()
        assert set(prov) == {
            "source_id",
            "modality",
            "authorship",
            "privacy",
            "license",
            "acquisition",
            "date_confidence",
        }

    def test_acquisition_has_method_ref_and_at(self):
        prov = default_provenance()
        assert set(prov["acquisition"]) == {"method", "ref", "at"}

    def test_overrides_are_applied(self):
        prov = default_provenance(modality="book", privacy="public")
        assert prov["modality"] == "book"
        assert prov["privacy"] == "public"

    def test_unknown_modality_raises(self):
        with pytest.raises(ValueError, match="modality"):
            default_provenance(modality="hieroglyph")

    def test_unknown_authorship_raises(self):
        with pytest.raises(ValueError, match="authorship"):
            default_provenance(authorship="ghostwriter")

    def test_vocabularies_are_closed(self):
        assert "article" in MODALITIES and "book" in MODALITIES
        assert AUTHORSHIPS == frozenset({"george", "mixed", "other"})


class TestMigrateArticles:
    def test_scraped_article_gets_forbes_provenance(self):
        articles = [{"slug": "a", "url": "https://forbes.com/x", "title": "A"}]
        out, count = migrate_articles(articles)
        assert count == 1
        prov = out[0]["provenance"]
        assert prov["modality"] == "article"
        assert prov["authorship"] == "george"
        assert prov["privacy"] == "public"
        assert prov["license"] == "forbes"
        assert prov["date_confidence"] == "exact"
        assert prov["acquisition"]["method"] == "scrape"

    def test_source_id_comes_from_slug(self):
        out, _ = migrate_articles([{"slug": "why-the-fed-blinked"}])
        assert out[0]["provenance"]["source_id"] == "why-the-fed-blinked"

    def test_acquisition_ref_is_the_url(self):
        out, _ = migrate_articles([{"slug": "a", "url": "https://forbes.com/x"}])
        assert out[0]["provenance"]["acquisition"]["ref"] == "https://forbes.com/x"

    def test_is_idempotent(self):
        articles = [{"slug": "a", "url": "u"}]
        once, first = migrate_articles(articles)
        twice, second = migrate_articles(once)
        assert first == 1
        assert second == 0
        assert once == twice

    def test_does_not_mutate_input(self):
        articles = [{"slug": "a"}]
        migrate_articles(articles)
        assert "provenance" not in articles[0]

    def test_preserves_existing_fields(self):
        out, _ = migrate_articles([{"slug": "a", "word_count": 42, "tags": ["fed"]}])
        assert out[0]["word_count"] == 42
        assert out[0]["tags"] == ["fed"]
