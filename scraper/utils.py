"""Shared utilities for the scraper: rate limiting, retry, slugify, logging."""

import logging
import re
import time
from functools import wraps
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the scraper logger."""
    logger = logging.getLogger("digital-dad.scraper")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger

log = setup_logging()

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Enforce a minimum delay between requests to the same domain."""

    # Domains that need longer delays to avoid rate-limit bans
    SLOW_DOMAINS = {"web.archive.org": 5.0}

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self._last_request: dict[str, float] = {}
        self._consecutive_errors: dict[str, int] = {}

    def wait(self, url: str) -> None:
        domain = urlparse(url).netloc
        base_delay = self.SLOW_DOMAINS.get(domain, self.delay)
        # Back off further if we've been getting errors
        errors = self._consecutive_errors.get(domain, 0)
        delay = base_delay * (1 + errors * 0.5)  # escalate on repeated errors

        now = time.monotonic()
        last = self._last_request.get(domain, 0.0)
        remaining = delay - (now - last)
        if remaining > 0:
            log.debug("Rate limiting: sleeping %.1fs for %s", remaining, domain)
            time.sleep(remaining)
        self._last_request[domain] = time.monotonic()

    def record_success(self, url: str) -> None:
        domain = urlparse(url).netloc
        self._consecutive_errors[domain] = 0

    def record_error(self, url: str) -> None:
        domain = urlparse(url).netloc
        self._consecutive_errors[domain] = self._consecutive_errors.get(domain, 0) + 1

rate_limiter = RateLimiter()

# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(max_attempts: int = 3, backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """Retry a function with exponential backoff."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        wait = backoff ** attempt
                        log.warning(
                            "Attempt %d/%d for %s failed (%s), retrying in %.1fs",
                            attempt, max_attempts, fn.__name__, exc, wait,
                        )
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------

def slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a URL/filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_length]

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

AUTHOR_URL = "https://www.forbes.com/sites/georgecalhoun/"

def is_article_url(url: str) -> bool:
    """Check if a URL looks like a Forbes article by George Calhoun."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    # Must be under /sites/georgecalhoun/ and have a slug after the author path
    if "/sites/georgecalhoun/" not in path:
        return False
    # Filter out /amp/ variants (duplicates of the main article)
    if "/amp" in path:
        return False
    # Filter out the author listing page itself
    after_author = path.split("/sites/georgecalhoun/")[-1].strip("/")
    if not after_author or after_author.startswith("?"):
        return False
    # Filter out pagination-like paths
    if after_author.isdigit():
        return False
    return True

def normalize_url(url: str) -> str:
    """Strip query params and fragments from a Forbes article URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"
