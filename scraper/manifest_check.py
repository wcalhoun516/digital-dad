"""Manifest integrity checker for the scraped corpus (roadmap #8).

Audits ``data/manifest.json`` against ``data/raw/*.json`` on disk and reports drift:
duplicate slugs / urls / content hashes, entries missing a ``content_hash``, manifest
entries whose raw file is missing, orphaned raw files no entry references, and a
``total_articles`` count that disagrees with the actual entry list.

The auditing logic is pure (``audit_manifest`` takes the manifest dict plus the set of
raw files present on disk) so it is unit-testable offline with no filesystem or network.
``main`` wires it to the real paths for ``python -m scraper.manifest_check`` / ``make
manifest-check``.
"""
