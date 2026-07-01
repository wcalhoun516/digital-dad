"""Coverage audit: what is the archive still missing? (roadmap #9)

Compares the set of article URLs we *have* (``data/manifest.json``) against a *discovered*
set — the author's full known Forbes footprint, sourced from the Wayback CDX index (or any
injected discovery source) — and reports what is missing: individual URLs absent from the
manifest, and the month-by-month date ranges where our coverage lags the discovered set.

The auditing logic is pure (``audit_coverage`` takes the manifest articles plus a list of
discovered URLs) so it is unit-testable offline with no network. ``run`` wires it to the live
Wayback discovery for ``python -m scraper.coverage_audit`` / ``make coverage-audit``.
"""

import re
from urllib.parse import urlparse

# Forbes author URLs encode the publish date + slug in the path:
#   /sites/georgecalhoun/YYYY/MM/DD/some-slug/
_ARTICLE_PATH = re.compile(
    r"/sites/georgecalhoun/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<slug>[^/]+)"
)


def parse_article_url(url: str) -> dict | None:
    """Parse a Forbes George-Calhoun article URL into its coverage fields.

    Returns ``{key, date, year, month, slug}`` where ``key`` is a canonical,
    scheme-/www-/query-insensitive identifier suitable for set comparison, or ``None`` when
    the URL is not a dated author article (listing pages, other authors, garbage).
    """
    if not url:
        return None
    try:
        path = urlparse(url).path
    except (ValueError, TypeError):
        return None
    match = _ARTICLE_PATH.search(path)
    if not match:
        return None
    y, m, d, slug = match.group("y"), match.group("m"), match.group("d"), match.group("slug")
    return {
        "key": f"georgecalhoun/{y}/{m}/{d}/{slug}",
        "date": f"{y}-{m}-{d}",
        "year": y,
        "month": f"{y}-{m}",
        "slug": slug,
    }


def audit_coverage(manifest_articles: list[dict], discovered_urls: list[str]) -> dict:
    """Compare what we *have* against a *discovered* footprint and report the gap.

    ``manifest_articles`` is the manifest's ``articles`` list (each with a ``url``);
    ``discovered_urls`` is the author's full known URL set (Wayback CDX or any source).
    Both are reduced to canonical keys via :func:`parse_article_url`; URLs that don't parse
    are collected separately (``unparsed_*``) rather than silently dropped. The report is a
    plain JSON-serializable dict; ``ok`` is True only when nothing discovered is missing.
    """
    have: dict[str, dict] = {}
    unparsed_manifest: list[str] = []
    for art in manifest_articles:
        url = art.get("url") or ""
        info = parse_article_url(url)
        if info is None:
            if url:
                unparsed_manifest.append(url)
        else:
            have.setdefault(info["key"], info)

    discovered: dict[str, dict] = {}
    unparsed_discovered: list[str] = []
    for url in discovered_urls:
        info = parse_article_url(url)
        if info is None:
            if url:
                unparsed_discovered.append(url)
        else:
            # First occurrence wins; keep the original URL for reporting.
            discovered.setdefault(info["key"], {**info, "url": url})

    have_keys = set(have)
    discovered_keys = set(discovered)
    missing_keys = discovered_keys - have_keys
    extra_keys = have_keys - discovered_keys

    missing_urls = sorted(
        (discovered[k] for k in missing_keys),
        key=lambda i: (i["date"], i["slug"]),
    )
    extra_urls = sorted(
        (have[k] for k in extra_keys),
        key=lambda i: (i["date"], i["slug"]),
    )

    months = sorted({i["month"] for i in have.values()} | {i["month"] for i in discovered.values()})
    by_month: dict[str, dict] = {}
    for month in months:
        h = sum(1 for i in have.values() if i["month"] == month)
        disc = sum(1 for i in discovered.values() if i["month"] == month)
        miss = sum(1 for i in missing_urls if i["month"] == month)
        by_month[month] = {"have": h, "discovered": disc, "missing": miss}

    gap_months = sorted(m for m, c in by_month.items() if c["missing"] > 0)

    discovered_count = len(discovered)
    matched_count = len(discovered_keys & have_keys)
    missing_count = len(missing_keys)
    coverage_ratio = matched_count / discovered_count if discovered_count else 1.0

    return {
        "have_count": len(have),
        "discovered_count": discovered_count,
        "matched_count": matched_count,
        "missing_count": missing_count,
        "extra_count": len(extra_keys),
        "coverage_ratio": coverage_ratio,
        "missing_urls": missing_urls,
        "extra_urls": extra_urls,
        "by_month": by_month,
        "gap_months": gap_months,
        "unparsed_manifest_urls": sorted(set(unparsed_manifest)),
        "unparsed_discovered_urls": sorted(set(unparsed_discovered)),
        "ok": missing_count == 0,
    }
