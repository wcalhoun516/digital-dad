"""Tier 3: Wayback Machine CDX API for discovering and fetching archived articles."""

import json
import re

import requests
from bs4 import BeautifulSoup

from .utils import log, rate_limiter, retry, is_article_url, normalize_url

CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"

# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def discover_urls_from_wayback() -> list[str]:
    """Query the Wayback Machine CDX API for all archived George Calhoun articles."""
    params = {
        "url": "forbes.com/sites/georgecalhoun/*",
        "output": "json",
        "fl": "original,timestamp,statuscode",
        "collapse": "urlkey",
        "filter": "statuscode:200",
        "limit": "5000",
    }

    rate_limiter.wait(CDX_API)
    try:
        resp = requests.get(CDX_API, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        log.error("Wayback CDX query failed: %s", exc)
        return []

    if not rows or len(rows) < 2:
        log.warning("No results from Wayback CDX API")
        return []

    # First row is the header
    header = rows[0]
    orig_idx = header.index("original")
    ts_idx = header.index("timestamp")

    urls: set[str] = set()
    for row in rows[1:]:
        original = row[orig_idx]
        if is_article_url(original):
            urls.add(normalize_url(original))

    log.info("Wayback CDX discovered %d article URLs", len(urls))
    return sorted(urls)

# ---------------------------------------------------------------------------
# Article extraction from Wayback
# ---------------------------------------------------------------------------

@retry(max_attempts=2, exceptions=(requests.RequestException,))
def extract_article_from_wayback(url: str) -> dict | None:
    """Fetch the most recent Wayback Machine snapshot of an article and extract content."""
    # Get the latest snapshot timestamp
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp",
        "sort": "timestamp:desc",
        "limit": "1",
        "filter": "statuscode:200",
    }

    rate_limiter.wait(CDX_API)
    try:
        resp = requests.get(CDX_API, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        log.error("Wayback timestamp lookup failed for %s: %s", url, exc)
        return None

    if len(rows) < 2:
        log.warning("No Wayback snapshot found for %s", url)
        return None

    timestamp = rows[1][0]
    wayback_url = f"{WAYBACK_PREFIX}/{timestamp}id_/{url}"

    rate_limiter.wait(wayback_url)
    try:
        resp = requests.get(wayback_url, timeout=20, headers={
            "User-Agent": "digital-dad-scraper/0.1 (research project)"
        })
        resp.raise_for_status()
    except Exception as exc:
        log.error("Wayback fetch failed for %s: %s", wayback_url, exc)
        return None

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

    # Body
    body_parts: list[str] = []
    for selector in ["article", ".article-body", ".body-container", '[class*="article-body"]']:
        container = soup.select_one(selector)
        if container:
            for p in container.find_all("p"):
                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    body_parts.append(text)
            if body_parts:
                break

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
        log.warning("No body text in Wayback snapshot for %s", url)
        return None

    return {
        "url": url,
        "title": title,
        "date": date,
        "body": body,
        "tags": tags,
        "word_count": len(body.split()),
        "source": "wayback",
        "wayback_timestamp": timestamp,
    }
