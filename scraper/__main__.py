"""CLI entry point: python -m scraper

Orchestrates three-tier scraping: Playwright → Sitemap → Wayback for URL discovery,
then requests+BS4 → Playwright → Wayback for content extraction.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .utils import log, slugify

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def load_manifest() -> dict:
    """Load existing manifest or return empty structure."""
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"last_updated": "", "total_articles": 0, "articles": []}


def save_manifest(manifest: dict) -> None:
    """Write manifest to disk."""
    manifest["last_updated"] = datetime.now(timezone.utc).isoformat()
    manifest["total_articles"] = len(manifest["articles"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("Manifest saved: %d articles", manifest["total_articles"])


def known_urls(manifest: dict) -> set[str]:
    """Get the set of already-scraped URLs."""
    return {a["url"] for a in manifest["articles"]}


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def discover_urls(use_playwright: bool = True) -> list[str]:
    """Discover article URLs using all available tiers."""
    all_urls: set[str] = set()

    # Tier 1: Playwright
    if use_playwright:
        try:
            from .forbes_playwright import discover_article_urls
            log.info("=== Tier 1: Playwright URL discovery ===")
            urls = asyncio.run(discover_article_urls(headless=True))
            all_urls.update(urls)
            log.info("Playwright found %d URLs", len(urls))
        except Exception as exc:
            log.warning("Playwright discovery failed: %s", exc)

    # Tier 2: Sitemap
    try:
        from .forbes_requests import discover_urls_from_sitemap
        log.info("=== Tier 2: Sitemap URL discovery ===")
        urls = discover_urls_from_sitemap()
        new = len(urls - all_urls) if isinstance(urls, set) else len(set(urls) - all_urls)
        all_urls.update(urls)
        log.info("Sitemap added %d new URLs (total: %d)", new, len(all_urls))
    except Exception as exc:
        log.warning("Sitemap discovery failed: %s", exc)

    # Tier 3: Wayback Machine
    try:
        from .wayback import discover_urls_from_wayback
        log.info("=== Tier 3: Wayback URL discovery ===")
        urls = discover_urls_from_wayback()
        new = len(set(urls) - all_urls)
        all_urls.update(urls)
        log.info("Wayback added %d new URLs (total: %d)", new, len(all_urls))
    except Exception as exc:
        log.warning("Wayback discovery failed: %s", exc)

    return sorted(all_urls)


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

def extract_article(url: str) -> dict | None:
    """Try to extract an article using all tiers: requests → Playwright → Wayback."""
    # Tier 2 first (fastest, lightest)
    try:
        from .forbes_requests import extract_article as requests_extract
        result = requests_extract(url)
        if result and result.get("body"):
            log.info("  ✓ Extracted via requests: %s", result.get("title", "")[:60])
            return result
    except Exception as exc:
        log.debug("  requests extraction failed: %s", exc)

    # Tier 1: Playwright (heavier but handles JS)
    try:
        from .forbes_playwright import extract_article as playwright_extract
        result = asyncio.run(playwright_extract(url, headless=True))
        if result and result.get("body"):
            log.info("  ✓ Extracted via Playwright: %s", result.get("title", "")[:60])
            return result
    except Exception as exc:
        log.debug("  Playwright extraction failed: %s", exc)

    # Tier 3: Wayback Machine
    try:
        from .wayback import extract_article_from_wayback
        result = extract_article_from_wayback(url)
        if result and result.get("body"):
            log.info("  ✓ Extracted via Wayback: %s", result.get("title", "")[:60])
            return result
    except Exception as exc:
        log.debug("  Wayback extraction failed: %s", exc)

    log.error("  ✗ All extraction tiers failed for %s", url)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Dr. George Calhoun's Forbes articles"
    )
    parser.add_argument("--limit", type=int, default=0, help="Max articles to scrape (0=all)")
    parser.add_argument("--force", action="store_true", help="Re-scrape already known articles")
    parser.add_argument("--no-playwright", action="store_true", help="Skip Playwright tier")
    parser.add_argument("--discover-only", action="store_true", help="Only discover URLs, don't extract")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        log.setLevel("DEBUG")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    already_scraped = known_urls(manifest)

    # Step 1: Discover URLs
    log.info("========== URL Discovery ==========")
    urls = discover_urls(use_playwright=not args.no_playwright)

    if not urls:
        log.error("No article URLs discovered. Check your network and try again.")
        sys.exit(1)

    log.info("Discovered %d total article URLs", len(urls))

    if args.discover_only:
        for url in urls:
            status = "✓" if url in already_scraped else "·"
            print(f"  {status} {url}")
        print(f"\nTotal: {len(urls)} URLs ({len(already_scraped)} already scraped)")
        return

    # Step 2: Filter to unscraped URLs
    if args.force:
        to_scrape = urls
    else:
        to_scrape = [u for u in urls if u not in already_scraped]

    if args.limit > 0:
        to_scrape = to_scrape[: args.limit]

    log.info("Will scrape %d articles (%d already in manifest)", len(to_scrape), len(already_scraped))

    # Step 3: Extract articles
    success = 0
    failed = 0
    consecutive_failures = 0
    for i, url in enumerate(to_scrape, 1):
        # Cooldown: if we've failed many in a row, Wayback is likely rate-limiting us
        if consecutive_failures >= 5:
            cooldown = min(120, 30 * (consecutive_failures // 5))
            log.warning(
                "⏸  %d consecutive failures — cooling down for %ds to avoid IP ban",
                consecutive_failures, cooldown,
            )
            time.sleep(cooldown)
            consecutive_failures = 0  # reset after cooldown

        log.info("[%d/%d] Extracting: %s", i, len(to_scrape), url)
        article = extract_article(url)

        if article is None:
            failed += 1
            consecutive_failures += 1
            continue

        consecutive_failures = 0

        # Save raw article JSON
        slug = slugify(article.get("title", "") or url.split("/")[-2])
        filename = f"{slug}.json"
        article["slug"] = slug
        article["scraped_at"] = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.md5((article.get("body") or "").encode()).hexdigest()

        (RAW_DIR / filename).write_text(
            json.dumps(article, indent=2, ensure_ascii=False)
        )

        # Update manifest
        manifest_entry = {
            "slug": slug,
            "title": article.get("title", ""),
            "date": article.get("date", ""),
            "url": url,
            "tags": article.get("tags", []),
            "word_count": article.get("word_count", 0),
            "file": f"raw/{filename}",
            "content_hash": content_hash,
        }

        # Replace existing entry or append
        existing_idx = next(
            (i for i, a in enumerate(manifest["articles"]) if a["url"] == url), None
        )
        if existing_idx is not None:
            manifest["articles"][existing_idx] = manifest_entry
        else:
            manifest["articles"].append(manifest_entry)

        success += 1

        # Save manifest periodically
        if success % 10 == 0:
            save_manifest(manifest)

    # Final save
    save_manifest(manifest)

    log.info("========== Scraping Complete ==========")
    log.info("Success: %d | Failed: %d | Total in manifest: %d", success, failed, manifest["total_articles"])


if __name__ == "__main__":
    main()
