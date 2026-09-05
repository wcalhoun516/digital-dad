"""Email handler for ``.eml`` and ``.mbox`` — stdlib only (roadmap #32).

An mbox is the canonical case of the design's "one source yields many documents" rule:
each message becomes its own document, sharing the thread's ``source_id``.

What reaches the corpus is the part Dr. Calhoun actually wrote — quoted replies,
attribution lines and signature blocks are stripped, because a thread that keeps its
quotes would count the same sentence once per reply.
"""

import mailbox
import re
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path

from ingest.extract import ExtractResult, empty_meta, register

_QUOTED_LINE = re.compile(r"^\s*>")
_ATTRIBUTION_OPENER = re.compile(r"^\s*On\b")
_ATTRIBUTION = re.compile(r"^\s*On\b.*\bwrote:\s*$")
_ORIGINAL_MESSAGE = re.compile(r"^\s*-+\s*Original Message\s*-+\s*$", re.IGNORECASE)
_SIGNATURE = re.compile(r"^--\s*$")
_BLANK_RUN = re.compile(r"\n{3,}")


def strip_quoted_reply(text: str) -> str:
    """Return only the newly-written part of a message body.

    Truncates at an attribution line (``On … wrote:``, ``-----Original Message-----``) or a
    ``--`` signature marker, then drops any remaining ``>`` quoted lines.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        if _is_attribution(lines, index) or _ORIGINAL_MESSAGE.match(line) or _SIGNATURE.match(line):
            break
        if _QUOTED_LINE.match(line):
            continue
        kept.append(line)
    return _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()


def _is_attribution(lines: list[str], index: int) -> bool:
    """Whether ``lines[index]`` opens an ``On … wrote:`` attribution.

    Gmail hard-wraps long attributions, so ``wrote:`` can land up to two lines below the
    ``On``; matching only single lines leaves a dangling recipient address in the body.
    """
    if not _ATTRIBUTION_OPENER.match(lines[index]):
        return False
    joined = lines[index]
    for line in lines[index + 1 : index + 3]:
        if _ATTRIBUTION.match(joined):
            return True
        joined = f"{joined} {line.strip()}"
    return bool(_ATTRIBUTION.match(joined))


def _body_text(message) -> str | None:
    """The message's ``text/plain`` content, or None when it carries no text part."""
    try:
        part = message.get_body(preferencelist=("plain",))
    except Exception:
        return None
    if part is None:
        return None
    try:
        return part.get_content()
    except Exception:
        return None


def _header(message, name: str) -> str:
    value = message.get(name)
    return "" if value is None else str(value).strip()


def _iso_date(message) -> str:
    """The ``Date`` header as ``YYYY-MM-DD``, or "" when absent or unparseable."""
    raw = _header(message, "Date")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _sender(message) -> str:
    return parseaddr(_header(message, "From"))[1].lower()


def _messages(path: Path) -> list:
    """Every message in the file, as policy-default ``EmailMessage`` objects."""
    if path.suffix.lower() == ".mbox":
        box = mailbox.mbox(str(path), create=False)
        try:
            raw = [message.as_bytes() for message in box]
        finally:
            box.close()
    else:
        raw = [path.read_bytes()]
    return [message_from_bytes(blob, policy=policy.default) for blob in raw]


@register(".eml", ".mbox")
def extract_mail(path: Path) -> ExtractResult:
    """Extract one document per message from an ``.eml`` or ``.mbox`` file."""
    path = Path(path)
    messages = _messages(path)

    documents: list[dict] = []
    warnings: list[str] = []
    dates: list[str] = []
    senders: set[str] = set()
    dropped = 0

    for message in messages:
        sender = _sender(message)
        if sender:
            senders.add(sender)
        date = _iso_date(message)
        if date:
            dates.append(date)

        body = _body_text(message)
        if body is None:
            dropped += 1
            warnings.append("message has no text part")
            continue

        text = strip_quoted_reply(body)
        if not text:
            dropped += 1
            continue

        documents.append(
            {
                "title": _header(message, "Subject") or path.stem,
                "text": text,
                "ordinal": len(documents),
            }
        )

    is_mbox = path.suffix.lower() == ".mbox"
    title = path.stem if is_mbox else (_header(messages[0], "Subject") if messages else "")
    meta = empty_meta(title or path.stem)
    meta["modality"] = "email"
    if len(senders) > 1:
        meta["authorship"] = "mixed"
    if dates:
        meta["date"] = min(dates)
        meta["date_confidence"] = "exact"
    else:
        warnings.append("no usable Date header")

    if not messages:
        warnings.append("mailbox is empty")
    elif dropped:
        warnings.append(f"{dropped} empty message(s) dropped")

    if not documents:
        return ExtractResult(documents=[], meta=meta, confidence=0.0, warnings=warnings)
    return ExtractResult(
        documents=documents,
        meta=meta,
        confidence=0.8 if warnings else 1.0,
        warnings=warnings,
    )
