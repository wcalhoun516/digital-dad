"""Validation for operator-console file uploads (plan 0011 step 2).

Nothing here touches HTTP. The console route is a thin caller; this module is the single
place that decides whether a client-supplied file is allowed to become a path on disk.
"""

from pathlib import Path

from ingest.extract import HANDLERS
from ingest.queue import INBOX_DIR

MAX_FILENAME_LEN = 255
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_SEPARATORS = ("/", "\\", ":")


class UploadRejected(Exception):
    """An upload was refused. The message is safe to show the operator."""


def sanitize_filename(name: str) -> str:
    """Return ``name`` trimmed, or raise ``UploadRejected`` if it is not a safe bare name.

    This never *repairs* a name. A client that sends a path has either a broken uploader or
    bad intent, and silently rewriting it into something valid hides both.
    """
    trimmed = (name or "").strip()

    def reject(reason: str):
        raise UploadRejected(f"{reason}: {name!r}")

    if not trimmed:
        reject("empty filename")
    if len(trimmed) > MAX_FILENAME_LEN:
        reject(f"filename longer than {MAX_FILENAME_LEN} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in trimmed):
        reject("filename contains control characters")
    # Rejecting every separator is what makes traversal impossible: a name with no "/",
    # "\" or ":" cannot address a directory at all, so no explicit ".." rule is needed.
    if any(sep in trimmed for sep in _SEPARATORS):
        reject("filename contains a path separator")
    if trimmed.startswith("."):
        reject("filename starts with a dot")
    return trimmed


def validate_upload(filename: str, size: int) -> str:
    """Return the safe name for an upload of ``size`` bytes, or raise ``UploadRejected``.

    The extension allowlist is read from the live handler registry rather than restated
    here, so registering a handler is the only edit needed to accept a new format.
    """
    name = sanitize_filename(filename)

    suffix = Path(name).suffix.lower()
    if suffix not in HANDLERS:
        raise UploadRejected(
            f"no ingest handler for {suffix or '(no extension)'}: {filename!r}"
        )

    if size <= 0:
        raise UploadRejected(f"empty upload: {filename!r}")
    if size > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"upload is {size} bytes, over the {MAX_UPLOAD_BYTES}-byte cap: {filename!r}"
        )
    return name


def _free_path(inbox: Path, name: str) -> Path:
    """Return a path under ``inbox`` that does not exist yet, suffixing on collision."""
    candidate = inbox / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while (candidate := inbox / f"{stem}-{counter}{suffix}").exists():
        counter += 1
    return candidate


def stage_upload(filename: str, data: bytes, inbox: Path = INBOX_DIR) -> Path:
    """Validate ``data`` and write it into ``inbox``. Returns the path written.

    The size cap is applied to the payload, never to a client-supplied length. An upload
    that collides with an existing name is written alongside it, never over it: the inbox
    holds the operator's only copy of material that may not exist anywhere else.
    """
    name = validate_upload(filename, len(data))
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    path = _free_path(inbox, name)
    path.write_bytes(data)
    return path
