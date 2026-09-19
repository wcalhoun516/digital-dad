"""Shared conductor preflight (roadmap #6).

Every owner-gated CLI that makes conductor calls (``rag_eval``, ``voice_eval``,
``verdict_backfill``, …) needs the same two things before it spends a paid T3
request: a cheap health check, and one clear "it's down, here's what to do"
message. This module is the single home for both, replacing three byte-for-byte
copies of ``_conductor_up()`` and their hand-written messages.

The health check GETs ``/models`` (cheap — no model load) and treats any
connection error or non-200 as "down". The only network call sits behind an
injectable ``opener`` so callers' tests can exercise the gating offline.
"""

import sys
from urllib.error import URLError
from urllib.request import urlopen

CONDUCTOR_BASE_URL = "http://127.0.0.1:8080/v1"


class PrivateContentError(RuntimeError):
    """Raised when a remote (T3) call would carry private corpus material off the machine."""


def _privacy_of(source: dict) -> tuple[str, str]:
    """Read ``(source_id, privacy)`` from a provenance block *or* a whole article dict.

    Anything it cannot read as an explicit ``"public"`` comes back private: a manifest
    entry written before the provenance schema, or a typo'd vocabulary value, must not be
    mistaken for a published column.
    """
    provenance = source.get("provenance") if "provenance" in source else source
    provenance = provenance or {}
    source_id = provenance.get("source_id") or source.get("slug") or "(unidentified)"
    privacy = "public" if provenance.get("privacy") == "public" else "private"
    return source_id, privacy


def assert_remote_allowed(sources: list[dict] | None) -> None:
    """Refuse a paid remote (T3) call that would carry private corpus material off the box.

    ``sources`` is what the prompt is built from — provenance blocks or article dicts.
    It **fails closed**: ``None`` means the caller never declared its inputs and is
    refused. ``[]`` is the explicit, reviewable way to say "no corpus material here"
    (a judge ranking model-generated text, for instance).
    """
    if sources is None:
        raise PrivateContentError(
            "Refusing a remote (T3) call: the caller did not declare what it is sending. "
            "Pass sources=[...] naming the corpus material in the prompt, or sources=[] "
            "if the prompt contains none."
        )
    private = [sid for sid, privacy in map(_privacy_of, sources) if privacy != "public"]
    if private:
        raise PrivateContentError(
            "Refusing a remote (T3) call: it would send private material to OpenRouter — "
            + ", ".join(private)
            + ". Re-run on a local tier (--judge-tier 2), or correct the provenance with "
            "`python -m ingest.review` if these are genuinely public."
        )


def conductor_up(base_url: str = CONDUCTOR_BASE_URL, timeout: float = 4, opener=None) -> bool:
    """Return True iff the conductor answers ``GET /models`` with HTTP 200.

    ``opener`` defaults to ``urllib.request.urlopen``; tests inject a fake.
    """
    open_url = opener or urlopen
    url = base_url.rstrip("/") + "/models"
    try:
        with open_url(url, timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def unreachable_message(base_url: str = CONDUCTOR_BASE_URL, extra: str = "") -> str:
    """The shared "conductor is down" message; ``extra`` appends a caller hint."""
    host = base_url.rstrip("/").removesuffix("/v1")
    msg = (
        f"Conductor is unreachable at {host} — start it before running this "
        "(the eval makes conductor calls, and the judge pass defaults to paid T3). Aborting."
    )
    if extra:
        msg += " " + extra
    return msg


def require_conductor(
    base_url: str = CONDUCTOR_BASE_URL,
    timeout: float = 4,
    extra: str = "",
    stream=None,
    opener=None,
) -> bool:
    """Gate a paid run on conductor reachability.

    Returns True if up. If down, prints :func:`unreachable_message` to ``stream``
    (default stdout) and returns False, so callers do ``if not require_conductor(): return 2``.
    """
    if conductor_up(base_url=base_url, timeout=timeout, opener=opener):
        return True
    print(unreachable_message(base_url=base_url, extra=extra), file=stream or sys.stdout)
    return False


def main(argv: list[str] | None = None) -> int:
    """`python -m analysis.conductor` — preflight check. Exit 0 up, 2 down."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m analysis.conductor",
        description="Conductor preflight: check the local LLM conductor is reachable. "
                    "Exit 0 if up, 2 if down (usable as a gate in scripts / make).",
    )
    parser.add_argument("--base-url", default=CONDUCTOR_BASE_URL,
                        help="conductor OpenAI-compatible base URL "
                             f"(default: {CONDUCTOR_BASE_URL})")
    parser.add_argument("--timeout", type=float, default=4,
                        help="health-check timeout in seconds (default: 4)")
    args = parser.parse_args(argv)

    if conductor_up(base_url=args.base_url, timeout=args.timeout):
        print(f"Conductor is up at {args.base_url.rstrip('/').removesuffix('/v1')}.")
        return 0
    print(unreachable_message(base_url=args.base_url))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
