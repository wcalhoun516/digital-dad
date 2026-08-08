"""Manifest de-dup / repair tool for the scraped corpus (roadmap #8 follow-up).

``scraper.manifest_check`` (#8) *reports* manifest drift; this module is the fix it
exposes. The root cause lives in ``scraper/__main__.py``: the scraper upserts manifest
entries keyed on **URL**, so an article rediscovered under a URL variant (query string,
scheme, trailing slash) appends a *second* entry with the same slug. On the real corpus
that produced 23 duplicate slugs.

``dedup_articles`` collapses entries that share a slug down to one canonical entry, and
``backfill_hashes`` fills a missing ``content_hash`` from the raw body on disk. Both are
pure (the raw-body lookup is an injected seam) so they are unit-testable offline.

The CLI is **report-only by default** (exit 0, mutates nothing), mirroring
``manifest_check`` / ``coverage_audit``. ``--apply`` writes the repaired manifest to a
*separate* file unless the owner passes ``--in-place``.
"""

import argparse
import hashlib
import json
import sys
from collections import OrderedDict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
RAW_DIR = DATA_DIR / "raw"


def content_hash_for(body: str | None) -> str:
    """MD5 of an article body, matching the scraper's ``content_hash`` convention."""
    return hashlib.md5((body or "").encode()).hexdigest()


def _entry_sort_key(entry: dict, index: int) -> tuple:
    """Rank a manifest entry within a same-slug group; smallest wins (is kept).

    Prefers an entry that (1) has a ``content_hash`` (real scraped content), then (2) a
    URL with no query string, then (3) https over http, then (4) a shorter URL, then (5)
    first-seen order — a fully deterministic canonical pick.
    """
    url = entry.get("url", "") or ""
    return (
        0 if entry.get("content_hash") else 1,
        1 if "?" in url else 0,
        0 if url.startswith("https://") else 1,
        len(url),
        index,
    )


def dedup_articles(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse manifest entries that share a (non-empty) slug down to one.

    Returns ``(deduped, actions)``. ``deduped`` preserves the first-seen order of the
    kept entries; entries with an empty/missing slug are passed through untouched.
    ``actions`` records one dict per collapsed slug: ``{slug, kept_url, dropped_urls}``.
    """
    groups: "OrderedDict[object, list[tuple[int, dict]]]" = OrderedDict()
    for index, entry in enumerate(articles):
        slug = entry.get("slug", "")
        # Empty-slug entries can't be de-duped by slug; key each on its identity so they
        # each form their own singleton group and pass through unchanged.
        key = slug if slug else (index, "__no_slug__")
        groups.setdefault(key, []).append((index, entry))

    deduped: list[dict] = []
    actions: list[dict] = []
    for key, members in groups.items():
        if len(members) == 1:
            deduped.append(members[0][1])
            continue
        kept_index, kept = min(members, key=lambda m: _entry_sort_key(m[1], m[0]))
        deduped.append(kept)
        dropped_urls = [
            e.get("url", "") for i, e in members if i != kept_index
        ]
        actions.append(
            {
                "slug": kept.get("slug", ""),
                "kept_url": kept.get("url", ""),
                "dropped_urls": dropped_urls,
            }
        )
    return deduped, actions


def backfill_hashes(articles: list[dict], read_body) -> tuple[list[dict], int]:
    """Fill a missing ``content_hash`` from the raw body on disk.

    ``read_body(file_field)`` is an injected seam returning the article body for an
    entry's ``file`` path (or ``None`` if unavailable) — so this stays offline-testable.
    Returns ``(articles, filled_count)``; entries that already have a hash are untouched.
    """
    filled = 0
    out: list[dict] = []
    for entry in articles:
        if not entry.get("content_hash"):
            body = read_body(entry.get("file", ""))
            if body is not None:
                entry = {**entry, "content_hash": content_hash_for(body)}
                filled += 1
        out.append(entry)
    return out, filled


def format_dedup_report(
    original: list[dict], deduped: list[dict], actions: list[dict]
) -> str:
    """Render a human-readable summary of what de-dup would change."""
    lines = [f"Manifest: {len(original)} entries → {len(deduped)} after de-dup."]
    if not actions:
        lines.append("OK — no duplicate slugs to collapse.")
        return "\n".join(lines)
    lines.append(f"Would collapse {len(actions)} duplicate slug group(s):")
    for a in sorted(actions, key=lambda x: x["slug"]):
        lines.append(f"  {a['slug']}: keep {a['kept_url']}")
        for u in a["dropped_urls"]:
            lines.append(f"    drop {u}")
    return "\n".join(lines)


def _read_body_from_disk(raw_dir: Path):
    def reader(file_field: str) -> str | None:
        if not file_field:
            return None
        # ``file`` is stored as ``raw/<name>.json`` relative to data/.
        path = raw_dir.parent / file_field
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text()).get("body")
        except (json.JSONDecodeError, OSError):
            return None

    return reader


def run(
    manifest_path: Path = MANIFEST_PATH,
    raw_dir: Path = RAW_DIR,
    *,
    apply: bool = False,
    in_place: bool = False,
    output: Path | None = None,
    backfill: bool = False,
) -> int:
    """De-dup the manifest at ``manifest_path``. Report-only unless ``apply`` is set.

    With ``apply`` the repaired manifest is written to ``output`` (default
    ``<manifest>.dedup.json``) — or over the original when ``in_place`` is set. Returns 1
    if the manifest is missing, else 0.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}. Run `make scrape` first.")
        return 1

    manifest = json.loads(manifest_path.read_text())
    articles = manifest.get("articles", [])
    deduped, actions = dedup_articles(articles)

    filled = 0
    if backfill:
        deduped, filled = backfill_hashes(deduped, _read_body_from_disk(Path(raw_dir)))

    print(format_dedup_report(articles, deduped, actions))
    if backfill:
        print(f"Backfilled content_hash for {filled} entr(y|ies) from raw bodies.")

    if not apply:
        print("\n(report only — pass --apply to write; nothing changed.)")
        return 0

    repaired = {**manifest, "articles": deduped, "total_articles": len(deduped)}
    dest = manifest_path if in_place else (output or _default_output(manifest_path))
    Path(dest).write_text(json.dumps(repaired, indent=2, ensure_ascii=False))
    print(f"\nWrote de-duped manifest ({len(deduped)} entries) to {dest}.")
    return 0


def _default_output(manifest_path: Path) -> Path:
    return manifest_path.with_suffix(".dedup.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.manifest_dedup",
        description=(
            "Collapse duplicate-slug entries in data/manifest.json (the fix "
            "manifest_check only reports). Report-only by default."
        ),
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument(
        "--apply", action="store_true",
        help="Write the de-duped manifest (default: report only, change nothing).",
    )
    parser.add_argument(
        "--in-place", action="store_true",
        help="With --apply, overwrite data/manifest.json instead of a separate file.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="With --apply, the output path (default: <manifest>.dedup.json).",
    )
    parser.add_argument(
        "--backfill-hashes", action="store_true", dest="backfill",
        help="Also fill a missing content_hash from each entry's raw body on disk.",
    )
    args = parser.parse_args(argv)
    return run(
        args.manifest,
        args.raw_dir,
        apply=args.apply,
        in_place=args.in_place,
        output=args.output,
        backfill=args.backfill,
    )


if __name__ == "__main__":
    sys.exit(main())
