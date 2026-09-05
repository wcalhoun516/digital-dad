"""Extraction contract and handler registry (roadmap #30).

A handler is a **pure function** ``(Path) -> ExtractResult``: no network, no mutation of
its input, deterministic for a given file. That keeps every format trivially testable and
safe for the unattended nightly agent.

Adding a format is an isolated change: a new module under ``ingest/handlers/`` with a
``@register(...)`` decorator, plus its import in ``ingest/handlers/__init__.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class UnsupportedFormat(Exception):
    """No handler is registered for this file extension."""


@dataclass(frozen=True)
class ExtractResult:
    """What a handler recovered from one file.

    ``documents`` is the unit of *analysis* — a book yields one per chapter, an mbox one
    per message — each ``{"title": str, "text": str, "ordinal": int}``. ``meta`` describes
    the *source* as a whole. ``confidence`` is 0.0-1.0; ``warnings`` are human-readable
    strings surfaced first in review.
    """

    documents: list[dict]
    meta: dict
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)


HANDLERS: dict[str, Callable[[Path], ExtractResult]] = {}


def register(*extensions: str):
    """Register a handler for one or more lowercase extensions (including the dot)."""

    def decorator(func: Callable[[Path], ExtractResult]):
        for ext in extensions:
            HANDLERS[ext.lower()] = func
        return func

    return decorator


def handler_for(path: Path) -> Callable[[Path], ExtractResult] | None:
    """Return the handler for ``path``'s extension, or None if unsupported."""
    return HANDLERS.get(Path(path).suffix.lower())


def extract(path: Path) -> ExtractResult:
    """Run the registered handler for ``path``.

    Raises ``UnsupportedFormat`` if no handler matches — callers stage that as a skipped
    file rather than failing the whole run.
    """
    path = Path(path)
    handler = handler_for(path)
    if handler is None:
        raise UnsupportedFormat(f"no handler for {path.suffix or '(no extension)'}")
    return handler(path)


def empty_meta(title: str = "") -> dict:
    """The meta block a handler starts from, matching the provenance vocabulary."""
    return {
        "title": title,
        "date": "",
        "date_confidence": "unknown",
        "modality": "letter",
        "authorship": "george",
        "privacy": "private",
        "license": "personal",
    }


# Populate the registry. Kept at the bottom to avoid a circular import: handlers import
# `register` from this module.
from ingest import handlers  # noqa: E402,F401
