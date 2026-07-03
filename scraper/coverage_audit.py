"""Coverage audit: what is the archive still missing? (roadmap #9)

Compares the set of article URLs we *have* (``data/manifest.json``) against a *discovered*
set — the author's full known Forbes footprint, sourced from the Wayback CDX index (or any
injected discovery source) — and reports what is missing: individual URLs absent from the
manifest, and the month-by-month date ranges where our coverage lags the discovered set.

The auditing logic is pure (``audit_coverage`` takes the manifest articles plus a list of
discovered URLs) so it is unit-testable offline with no network. ``run`` wires it to the live
Wayback discovery for ``python -m scraper.coverage_audit`` / ``make coverage-audit``.
"""

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"

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


def contiguous_month_ranges(months: list[str]) -> list[str]:
    """Group ``YYYY-MM`` strings into consecutive-calendar-month ranges.

    A lone month renders bare (``"2021-03"``); a run of consecutive months renders as
    ``"start..end"`` (``"2021-12..2022-01"`` across a year boundary). Input is sorted and
    de-duplicated first, so callers needn't pre-sort.
    """
    def index(month: str) -> int:
        y, m = month.split("-")
        return int(y) * 12 + (int(m) - 1)

    ordered = sorted(set(months))
    ranges: list[str] = []
    start = prev = None
    for month in ordered:
        if start is None:
            start = prev = month
        elif index(month) == index(prev) + 1:
            prev = month
        else:
            ranges.append(start if start == prev else f"{start}..{prev}")
            start = prev = month
    if start is not None:
        ranges.append(start if start == prev else f"{start}..{prev}")
    return ranges


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
    missing_ranges = contiguous_month_ranges(gap_months)

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
        "missing_ranges": missing_ranges,
        "unparsed_manifest_urls": sorted(set(unparsed_manifest)),
        "unparsed_discovered_urls": sorted(set(unparsed_discovered)),
        "ok": missing_count == 0,
    }


def format_report(report: dict) -> str:
    """Render a coverage report as a human-readable, multi-line summary."""
    pct = report["coverage_ratio"] * 100
    lines = [
        f"Coverage: {report['matched_count']}/{report['discovered_count']} discovered "
        f"articles present ({pct:.1f}%); manifest holds {report['have_count']}.",
    ]

    if report["discovered_count"] == 0:
        lines.append(
            "  0 discovered — no URLs discovered to compare against "
            "(discovery source returned nothing; coverage unknown)."
        )

    if report["missing_count"] == 0:
        lines.append("  No missing articles — archive is complete vs the discovered set.")
    else:
        lines.append(
            f"  MISSING {report['missing_count']} article(s) across "
            f"{len(report['gap_months'])} month(s): {', '.join(report['missing_ranges'])}"
        )
        for miss in report["missing_urls"]:
            lines.append(f"    {miss['date']}  {miss['slug']}  ({miss['url']})")

    if report["extra_count"]:
        lines.append(
            f"  {report['extra_count']} manifest article(s) not in the discovered set "
            "(may be discovery gaps, not corpus errors)."
        )
    if report["unparsed_manifest_urls"]:
        lines.append(
            f"  {len(report['unparsed_manifest_urls'])} manifest URL(s) did not match the "
            "author-article pattern (skipped)."
        )
    if report["unparsed_discovered_urls"]:
        lines.append(
            f"  {len(report['unparsed_discovered_urls'])} discovered URL(s) did not match the "
            "author-article pattern (skipped)."
        )
    return "\n".join(lines)


def load_manifest_articles(path: Path) -> list[dict]:
    """Load the ``articles`` list from a manifest JSON file."""
    return json.loads(Path(path).read_text()).get("articles", [])


def read_urls_file(path: Path) -> list[str]:
    """Read a discovery URL list from a file: one URL per line, ``#`` comments/blanks ignored."""
    urls: list[str] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _default_discover() -> list[str]:
    """Live discovery source: the author's full footprint via the Wayback CDX index."""
    from .wayback import discover_urls_from_wayback

    return discover_urls_from_wayback()


def run(
    manifest_path: Path = MANIFEST_PATH,
    *,
    discover: Callable[[], list[str]] | None = None,
    urls_file: Path | None = None,
    as_json: bool = False,
    strict: bool = False,
) -> int:
    """Audit the manifest's coverage against a discovered author footprint and print it.

    Discovery source precedence: ``urls_file`` (offline list) → ``discover`` callable →
    live Wayback CDX. Returns 0 normally; 1 when the manifest is missing, or when ``strict``
    is set and articles are missing (so it can gate CI).
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}. Run `make scrape` first.")
        return 1

    if urls_file is not None:
        discovered = read_urls_file(urls_file)
    else:
        discovered = (discover or _default_discover)()

    report = audit_coverage(load_manifest_articles(manifest_path), discovered)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    if strict and not report["ok"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.coverage_audit",
        description="Audit corpus coverage vs the author's full Forbes footprint (roadmap #9).",
    )
    parser.add_argument(
        "--manifest", type=Path, default=MANIFEST_PATH,
        help="Path to manifest.json (default: data/manifest.json).",
    )
    parser.add_argument(
        "--urls-file", type=Path, default=None,
        help="Read the discovered URL set from a file (one per line) instead of querying "
             "Wayback — offline / reproducible input.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit the report as JSON instead of a human summary.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero when articles are missing (for CI).",
    )
    args = parser.parse_args(argv)
    return run(args.manifest, urls_file=args.urls_file, as_json=args.as_json, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
