"""Tests for ingest/provenance.py — the provenance vocabulary and defaults."""

import pytest

from ingest.provenance import (
    AUTHORSHIPS,
    MODALITIES,
    default_provenance,
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
