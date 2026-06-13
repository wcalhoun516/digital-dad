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

from collections import Counter


def audit_manifest(manifest: dict, raw_files_on_disk: set[str]) -> dict:
    """Audit a manifest dict against the raw files present on disk.

    ``raw_files_on_disk`` is the set of file paths (as stored in each entry's ``file``
    field, e.g. ``"raw/slug.json"``) that actually exist. The returned report is a plain
    JSON-serializable dict; ``ok`` is True only when ``issue_count`` is zero.
    """
    articles = manifest.get("articles", [])
    article_count = len(articles)
    declared_total = manifest.get("total_articles")

    slug_counts = Counter(a.get("slug", "") for a in articles)
    url_counts = Counter(a.get("url", "") for a in articles)

    duplicate_slugs = {s: n for s, n in slug_counts.items() if s and n > 1}
    duplicate_urls = {u: n for u, n in url_counts.items() if u and n > 1}

    hash_to_slugs: dict[str, list[str]] = {}
    missing_content_hash: list[str] = []
    for a in articles:
        slug = a.get("slug", "")
        h = a.get("content_hash") or ""
        if h:
            hash_to_slugs.setdefault(h, []).append(slug)
        else:
            missing_content_hash.append(slug)
    duplicate_content_hashes = {
        h: sorted(slugs) for h, slugs in hash_to_slugs.items() if len(slugs) > 1
    }

    referenced_files: set[str] = set()
    entries_missing_file_field: list[str] = []
    for a in articles:
        f = a.get("file") or ""
        if f:
            referenced_files.add(f)
        else:
            entries_missing_file_field.append(a.get("slug", ""))

    missing_files = sorted(referenced_files - raw_files_on_disk)
    orphaned_files = sorted(raw_files_on_disk - referenced_files)
    count_drift = declared_total != article_count

    issue_count = (
        len(duplicate_slugs)
        + len(duplicate_urls)
        + len(duplicate_content_hashes)
        + len(missing_content_hash)
        + len(missing_files)
        + len(orphaned_files)
        + len(entries_missing_file_field)
        + (1 if count_drift else 0)
    )

    return {
        "article_count": article_count,
        "declared_total": declared_total,
        "count_drift": count_drift,
        "duplicate_slugs": duplicate_slugs,
        "duplicate_urls": duplicate_urls,
        "duplicate_content_hashes": duplicate_content_hashes,
        "missing_content_hash": sorted(missing_content_hash),
        "entries_missing_file_field": sorted(entries_missing_file_field),
        "missing_files": missing_files,
        "orphaned_files": orphaned_files,
        "issue_count": issue_count,
        "ok": issue_count == 0,
    }


def format_report(report: dict) -> str:
    """Render an audit report as a human-readable, multi-line summary."""
    lines = [
        f"Manifest: {report['article_count']} entries "
        f"(declared total_articles: {report['declared_total']})",
    ]
    if report["ok"]:
        lines.append("OK — no integrity issues found.")
        return "\n".join(lines)

    lines.append(f"FOUND {report['issue_count']} issue group(s):")

    if report["count_drift"]:
        lines.append(
            f"  count drift: total_articles={report['declared_total']} "
            f"but {report['article_count']} entries present"
        )
    if report["duplicate_slugs"]:
        lines.append(f"  duplicate slugs ({len(report['duplicate_slugs'])}):")
        for slug, n in sorted(report["duplicate_slugs"].items()):
            lines.append(f"    {slug} ×{n}")
    if report["duplicate_urls"]:
        lines.append(f"  duplicate urls ({len(report['duplicate_urls'])}):")
        for url, n in sorted(report["duplicate_urls"].items()):
            lines.append(f"    {url} ×{n}")
    if report["duplicate_content_hashes"]:
        lines.append(
            f"  duplicate content_hash ({len(report['duplicate_content_hashes'])}):"
        )
        for h, slugs in sorted(report["duplicate_content_hashes"].items()):
            lines.append(f"    {h[:12]}…: {', '.join(slugs)}")
    if report["missing_content_hash"]:
        lines.append(
            f"  missing content_hash ({len(report['missing_content_hash'])}): "
            f"{', '.join(report['missing_content_hash'])}"
        )
    if report["entries_missing_file_field"]:
        lines.append(
            f"  entries missing file field ({len(report['entries_missing_file_field'])}): "
            f"{', '.join(report['entries_missing_file_field'])}"
        )
    if report["missing_files"]:
        lines.append(
            f"  referenced files absent on disk ({len(report['missing_files'])}): "
            f"{', '.join(report['missing_files'])}"
        )
    if report["orphaned_files"]:
        lines.append(
            f"  orphaned raw files (no manifest entry) ({len(report['orphaned_files'])}): "
            f"{', '.join(report['orphaned_files'])}"
        )
    return "\n".join(lines)
