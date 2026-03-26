"""Tier 2: requests + BeautifulSoup scraper for individual Forbes articles."""

import re
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from .utils import log, rate_limiter, retry, is_article_url, normalize_url

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ---------------------------------------------------------------------------
# URL discovery via sitemap
# ---------------------------------------------------------------------------

def discover_urls_from_sitemap() -> list[str]:
    """Try to find article URLs via Forbes sitemap XML."""
    urls: set[str] = set()

    try:
        # Forbes sitemap index
        rate_limiter.wait("https://www.forbes.com/sitemap_index.xml")
        resp = SESSION.get("https://www.forbes.com/sitemap_index.xml", timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        sitemap_urls = [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]
        log.info("Found %d sitemaps in index", len(sitemap_urls))

        # Look for sitemaps that might contain author articles
        for sitemap_url in sitemap_urls:
            if "georgecalhoun" in sitemap_url.lower() or "contributor" in sitemap_url.lower():
                rate_limiter.wait(sitemap_url)
                resp = SESSION.get(sitemap_url, timeout=15)
                if resp.ok:
                    sub_root = ET.fromstring(resp.text)
                    for loc in sub_root.findall(".//sm:loc", ns):
                        if loc.text and is_article_url(loc.text):
                            urls.add(normalize_url(loc.text))

        # Also try a direct contributor sitemap pattern
        for pattern in [
            "https://www.forbes.com/sitemap/georgecalhoun.xml",
            "https://www.forbes.com/sitemap_contributor_georgecalhoun.xml",
        ]:
            rate_limiter.wait(pattern)
            try:
                resp = SESSION.get(pattern, timeout=10)
                if resp.ok:
                    sub_root = ET.fromstring(resp.text)
                    ns2 = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                    for loc in sub_root.findall(".//sm:loc", ns2):
                        if loc.text and is_article_url(loc.text):
                            urls.add(normalize_url(loc.text))
            except Exception:
                pass

    except Exception as exc:
        log.warning("Sitemap discovery failed: %s", exc)

    log.info("Sitemap discovery found %d URLs", len(urls))
    return sorted(urls)

# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

@retry(max_attempts=3, exceptions=(requests.RequestException,))
def extract_article(url: str) -> dict | None:
    """Fetch and parse a single Forbes article page."""
    rate_limiter.wait(url)
    resp = SESSION.get(url, timeout=20)

    if resp.status_code == 403:
        log.warning("403 Forbidden for %s — may need Playwright or Wayback fallback", url)
        return None
    if resp.status_code == 503:
        log.warning("503 Service Unavailable for %s — Cloudflare block?", url)
        return None
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")

    # Date
    date = ""
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        date = time_tag["datetime"]
    if not date:
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date:
            date = meta_date.get("content", "")
    # Fallback: extract date from URL pattern /YYYY/MM/DD/
    if not date:
        date_match = re.search(r"/(\d{4}/\d{2}/\d{2})/", url)
        if date_match:
            date = date_match.group(1).replace("/", "-")

    # Body text — try multiple selectors
    body_parts: list[str] = []
    for selector in ["article", ".article-body", ".body-container", '[class*="article-body"]']:
        container = soup.select_one(selector)
        if container:
            for p in container.find_all("p"):
                text = p.get_text(strip=True)
                if text and len(text) > 20:  # skip short boilerplate fragments
                    body_parts.append(text)
            if body_parts:
                break

    # Fallback: all <p> tags in the page (less precise)
    if not body_parts:
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 50:
                body_parts.append(text)

    body = "\n\n".join(body_parts)

    # Tags
    tags = []
    for meta in soup.find_all("meta", property="article:tag"):
        tag = meta.get("content", "").strip()
        if tag:
            tags.append(tag)

    if not body:
        log.warning("No body text found for %s", url)
        return None

    return {
        "url": url,
        "title": title,
        "date": date,
        "body": body,
        "tags": tags,
        "word_count": len(body.split()),
    }
