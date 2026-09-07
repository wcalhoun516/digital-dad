"""Reading Room — a clean, paginated full-article reader for the family dashboard.

Roadmap #21 (dashboard / family-facing): assemble the corpus into an ordered,
navigable reading experience — every column with its full body, theme tag, prev/next
links, and a "read on Forbes" deep link — so the family can sit and *read* the archive,
not just query or chart it.

Deterministic and offline: joins the metadata already on disk (``themes.json`` for the
per-article theme label, the manifest for ordering/word counts) with the full article
bodies from ``data/raw/*.json``. Makes no conductor/network/LLM calls, so it is safe to
run unattended.

Licensing: the emitted ``reading_room.json`` embeds full article bodies, so — like
``embeddings.json`` and ``anthology.json`` — it is **git-ignored** and regenerated on
demand (``make reading-room``). Full text lives only in the owner's local build (and the
git-ignored ``dashboard/index.html``); it is never committed and never present in CI,
where the dashboard inlines an empty stub instead.
"""

import argparse
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from .utils import ANALYSIS_DIR, RAW_DIR

THEMES_PATH = ANALYSIS_DIR / "themes.json"
OUT_DIR = ANALYSIS_DIR

# Reading speed for the time-to-read estimate shown in the reader.
_WORDS_PER_MINUTE = 200


def paragraphs(body: str | None) -> list[str]:
    """Split a raw article body into clean paragraphs.

    Splits on blank lines, strips whitespace, and drops empties (raw Wayback bodies carry
    stray whitespace-only "paragraphs"). None/blank → ``[]``.
    """
    if not body or not body.strip():
        return []
    parts = re.split(r"\n\s*\n", body)
    return [p.strip() for p in parts if p.strip()]


def reading_time_minutes(word_count: int) -> int:
    """Estimated minutes to read, at ~200 wpm. A real article never rounds to 0."""
    if word_count <= 0:
        return 0
    return max(1, math.ceil(word_count / _WORDS_PER_MINUTE))


def build_reading_room(
    articles: list[dict],
    *,
    load_body: Callable[[str], str | None],
    limit: int | None = None,
) -> dict:
    """Assemble the ordered, navigable reading experience (pure; no I/O).

    ``articles`` is a ``themes.json``-shaped list (``slug``/``title``/``date``/``url``/
    ``word_count``/``cluster_label``). ``load_body(slug)`` returns the full body text or
    ``None`` when the raw file is missing. Entries are ordered **newest-first** by date;
    undated records (the Forbes author-listing page) and any article with no readable body
    are excluded (there is nothing to read). ``prev_slug``/``next_slug`` walk the final
    reading order. ``limit`` keeps the newest N.

    Repeated slugs collapse to their first record in reading order. The corpus manifest
    records ``http://``/``https://`` twins of the same article and they reach here through
    ``themes.json``; because the reader resolves ``prev_slug``/``next_slug`` through a
    slug-keyed map, a slug present twice would make a neighbour link resolve back to the
    article the reader is already on.
    """
    dated = [a for a in articles if (a.get("date") or "")]
    ordered = sorted(dated, key=lambda a: (a.get("date", ""), a.get("slug", "")), reverse=True)

    entries: list[dict] = []
    seen: set[str] = set()
    for a in ordered:
        slug = a.get("slug", "")
        if slug in seen:
            continue
        paras = paragraphs(load_body(slug))
        if not paras:
            continue
        seen.add(slug)
        entries.append(
            {
                "slug": slug,
                "title": a.get("title", ""),
                "date": a.get("date", ""),
                "url": a.get("url", ""),
                "theme": a.get("cluster_label", ""),
                "word_count": a.get("word_count", 0),
                "reading_minutes": reading_time_minutes(a.get("word_count", 0)),
                "paragraphs": paras,
                "prev_slug": None,
                "next_slug": None,
            }
        )
        if limit is not None and len(entries) >= limit:
            break

    for i, entry in enumerate(entries):
        entry["prev_slug"] = entries[i - 1]["slug"] if i > 0 else None
        entry["next_slug"] = entries[i + 1]["slug"] if i < len(entries) - 1 else None

    theme_counts = Counter(e["theme"] for e in entries)
    themes = [t for t, _ in sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {"entries": entries, "count": len(entries), "themes": themes}


def _load_json(path: Path, default):
    """Load JSON from ``path``; return ``default`` if it is missing or malformed."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _load_theme_articles() -> list[dict]:
    data = _load_json(THEMES_PATH, {})
    return data.get("articles", []) if isinstance(data, dict) else []


def _read_raw_body(slug: str, *, raw_dir: Path = RAW_DIR) -> str | None:
    """Read the full body text for ``slug`` from ``data/raw/<slug>.json``.

    Returns ``None`` if the file is missing or malformed — such articles simply don't appear
    in the reading room (there is nothing to read).
    """
    record = _load_json(Path(raw_dir) / f"{slug}.json", None)
    if not isinstance(record, dict):
        return None
    body = record.get("body")
    return body if isinstance(body, str) else None


def run(
    *,
    articles: list[dict] | None = None,
    load_body: Callable[[str], str | None] | None = None,
    out_dir: Path = OUT_DIR,
    write: bool = True,
    limit: int | None = None,
) -> dict:
    """Build the reading room and (unless ``write=False``) write it to disk.

    Deterministic and offline: reads ``themes.json`` for article metadata/theme labels and the
    full bodies from ``data/raw/*.json`` (or the injected ``articles``/``load_body``), then
    writes the **git-ignored** ``reading_room.json`` (full bodies — regenerate on demand).
    Makes no conductor/network/LLM calls.
    """
    if articles is None:
        articles = _load_theme_articles()
    if load_body is None:
        load_body = _read_raw_body

    room = build_reading_room(articles, load_body=load_body, limit=limit)

    json_file = None
    if write:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_file = out_dir / "reading_room.json"
        json_file.write_text(json.dumps(room, indent=2, ensure_ascii=False) + "\n")

    return {"reading_room": room, "json_file": str(json_file) if json_file else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reading Room — full-article reader data for the dashboard (roadmap #21)."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Keep only the newest N readable articles (default: all).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be built without writing reading_room.json.",
    )
    args = parser.parse_args(argv)

    result = run(write=not args.dry_run, limit=args.limit)
    room = result["reading_room"]
    print(f"Reading Room: {room['count']} readable articles across {len(room['themes'])} themes.")
    if result["json_file"]:
        print(f"JSON saved:  {result['json_file']}")
        print("Run `make dashboard` to surface it in the Reading Room tab.")
    else:
        print("Dry run — nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
