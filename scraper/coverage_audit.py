"""Coverage audit: what is the archive still missing? (roadmap #9)

Compares the set of article URLs we *have* (``data/manifest.json``) against a *discovered*
set — the author's full known Forbes footprint, sourced from the Wayback CDX index (or any
injected discovery source) — and reports what is missing: individual URLs absent from the
manifest, and the month-by-month date ranges where our coverage lags the discovered set.

The auditing logic is pure (``audit_coverage`` takes the manifest articles plus a list of
discovered URLs) so it is unit-testable offline with no network. ``run`` wires it to the live
Wayback discovery for ``python -m scraper.coverage_audit`` / ``make coverage-audit``.
"""
