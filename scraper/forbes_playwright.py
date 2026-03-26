"""Tier 1: Playwright-based scraper for Forbes author page (infinite scroll)."""

import json
import asyncio
from pathlib import Path

from .utils import log, rate_limiter, is_article_url, normalize_url, AUTHOR_URL

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BROWSER_STATE_DIR = DATA_DIR / ".browser-state"


async def discover_article_urls(headless: bool = True, max_scrolls: int = 200) -> list[str]:
    """Scroll the Forbes author page and collect all article URLs.

    Returns a deduplicated list of article URLs.
    """
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async
    except ImportError:
        log.error("playwright or playwright-stealth not installed. Run: pip install -e '.[scrape]'")
        return []

    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

    urls: set[str] = set()
    stale_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            storage_state=str(BROWSER_STATE_DIR / "state.json")
            if (BROWSER_STATE_DIR / "state.json").exists()
            else None,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await stealth_async(page)

        log.info("Navigating to %s", AUTHOR_URL)
        await page.goto(AUTHOR_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3000)

        for scroll_num in range(1, max_scrolls + 1):
            # Collect links before scrolling
            links = await page.eval_on_selector_all(
                "a[href*='/sites/georgecalhoun/']",
                "els => els.map(e => e.href)",
            )
            before = len(urls)
            for link in links:
                if is_article_url(link):
                    urls.add(normalize_url(link))

            new_count = len(urls) - before
            if new_count > 0:
                stale_count = 0
                log.info("Scroll %d: found %d new URLs (total: %d)", scroll_num, new_count, len(urls))
            else:
                stale_count += 1
                log.debug("Scroll %d: no new URLs (stale count: %d)", scroll_num, stale_count)

            if stale_count >= 3:
                log.info("No new articles after %d scrolls — stopping", stale_count)
                break

            # Scroll down and wait for content to load
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            # Also try clicking a "Load More" button if present
            try:
                load_more = page.locator("button:has-text('Load More'), a:has-text('Load More')")
                if await load_more.count() > 0:
                    await load_more.first.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

        # Save browser state for next run
        await context.storage_state(path=str(BROWSER_STATE_DIR / "state.json"))
        await browser.close()

    log.info("Playwright discovered %d article URLs", len(urls))
    return sorted(urls)


async def extract_article(url: str, headless: bool = True) -> dict | None:
    """Use Playwright to extract article content (fallback for JS-heavy pages)."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async
    except ImportError:
        return None

    rate_limiter.wait(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            storage_state=str(BROWSER_STATE_DIR / "state.json")
            if (BROWSER_STATE_DIR / "state.json").exists()
            else None,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2000)

            title = await page.title()
            # Try to get the article heading
            h1 = page.locator("h1")
            if await h1.count() > 0:
                title = (await h1.first.text_content() or title).strip()

            # Date
            date = ""
            time_el = page.locator("time[datetime]")
            if await time_el.count() > 0:
                date = await time_el.first.get_attribute("datetime") or ""
            if not date:
                meta_date = page.locator("meta[property='article:published_time']")
                if await meta_date.count() > 0:
                    date = await meta_date.first.get_attribute("content") or ""

            # Body text
            paragraphs = await page.eval_on_selector_all(
                "article p, .article-body p, .body-container p",
                "els => els.map(e => e.textContent.trim()).filter(t => t.length > 0)",
            )
            body = "\n\n".join(paragraphs)

            # Tags
            tags = await page.eval_on_selector_all(
                "meta[property='article:tag']",
                "els => els.map(e => e.getAttribute('content')).filter(Boolean)",
            )

            await context.storage_state(path=str(BROWSER_STATE_DIR / "state.json"))
            await browser.close()

            if not body:
                log.warning("No body text extracted from %s via Playwright", url)
                return None

            return {
                "url": url,
                "title": title,
                "date": date,
                "body": body,
                "tags": tags,
                "word_count": len(body.split()),
            }
        except Exception as exc:
            log.error("Playwright extraction failed for %s: %s", url, exc)
            await browser.close()
            return None
