"""Tests for the T3 private-document guard in analysis/conductor.py (roadmap #38).

Tier 3 is OpenRouter: the only tier where corpus text leaves the Mac mini and reaches a
third party. Until now nothing checked *what* was being sent. Once ``ingest`` starts
accepting letters, emails and books, "send the article body to the judge" silently becomes
"send his private correspondence to a vendor".

The guard is pure and offline — it inspects provenance dicts and raises. These tests make
no network call.
"""

import pytest

from analysis.conductor import PrivateContentError, assert_remote_allowed
from ingest.provenance import default_provenance

PUBLIC = default_provenance(source_id="a-forbes-column", privacy="public", license="forbes")
PRIVATE = default_provenance(source_id="a-letter", modality="letter", privacy="private")


# --------------------------------------------------------------------------- #
# Fail closed: silence is never consent
# --------------------------------------------------------------------------- #

def test_unstated_sources_refuse():
    """``None`` means the caller never said what it was sending — that must not pass."""
    with pytest.raises(PrivateContentError) as excinfo:
        assert_remote_allowed(None)
    assert "did not declare" in str(excinfo.value)


def test_explicitly_no_corpus_material_is_allowed():
    """An empty list is a caller stating "nothing from the corpus is in this prompt"."""
    assert_remote_allowed([]) is None


# --------------------------------------------------------------------------- #
# The actual policy
# --------------------------------------------------------------------------- #

def test_public_sources_are_allowed():
    assert_remote_allowed([PUBLIC, PUBLIC]) is None


def test_a_single_private_source_refuses_the_whole_call():
    with pytest.raises(PrivateContentError):
        assert_remote_allowed([PUBLIC, PRIVATE, PUBLIC])


def test_refusal_names_the_offending_source_ids():
    """The owner must be able to see *which* document blocked the call."""
    with pytest.raises(PrivateContentError) as excinfo:
        assert_remote_allowed([PUBLIC, PRIVATE])
    message = str(excinfo.value)
    assert "a-letter" in message
    assert "a-forbes-column" not in message


def test_refusal_names_every_offending_source_not_just_the_first():
    second = default_provenance(source_id="another-letter", privacy="private")
    with pytest.raises(PrivateContentError) as excinfo:
        assert_remote_allowed([PRIVATE, second])
    message = str(excinfo.value)
    assert "a-letter" in message
    assert "another-letter" in message


# --------------------------------------------------------------------------- #
# Malformed provenance is treated as private, not as "fine"
# --------------------------------------------------------------------------- #

def test_missing_privacy_key_is_treated_as_private():
    """An entry predating the provenance schema must not be read as public by default."""
    with pytest.raises(PrivateContentError):
        assert_remote_allowed([{"source_id": "legacy-entry"}])


def test_unknown_privacy_value_is_treated_as_private():
    with pytest.raises(PrivateContentError):
        assert_remote_allowed([{"source_id": "odd", "privacy": "PUBLIC"}])


def test_a_bare_article_dict_carrying_provenance_is_unwrapped():
    """Callers hold articles, not provenance blocks — accept either shape."""
    article = {"slug": "a-forbes-column", "body": "...", "provenance": PUBLIC}
    assert_remote_allowed([article]) is None


def test_an_article_dict_with_no_provenance_at_all_refuses():
    with pytest.raises(PrivateContentError) as excinfo:
        assert_remote_allowed([{"slug": "unmigrated", "body": "..."}])
    assert "unmigrated" in str(excinfo.value)
