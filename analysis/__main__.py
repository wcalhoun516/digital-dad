"""CLI entry point: python -m analysis

Runs all analysis modules or individual ones. All LLM calls route through
the local-llm-conductor at http://127.0.0.1:8080.

Examples:
  python -m analysis                    # run all modules (default: T2 local for psychoprofile)
  python -m analysis linguistic themes  # run specific modules
  python -m analysis psychoprofile             # T2 local LLM (default)
  python -m analysis psychoprofile --remote    # T3 remote model via conductor (costs money)
  python -m analysis --dry-run          # estimate costs only
  python -m analysis --force            # re-run even if no articles changed
  python -m analysis --verbose          # DEBUG-level logging (e.g. per-k silhouette scores)
"""

import argparse
import hashlib
import json
import sys

from .utils import DATA_DIR, load_articles, log

RUNS_LOG = DATA_DIR / "analysis" / "runs.jsonl"
ALL_MODULES = ["linguistic", "themes", "entities", "psychoprofile", "semantic_search", "predictions"]


def _corpus_fingerprint(articles: list[dict]) -> str:
    """Return an MD5 of all article slugs+content_hashes to detect corpus changes."""
    parts = []
    for a in sorted(articles, key=lambda x: x.get("slug", "")):
        # Use existing content_hash if present, else hash body
        h = a.get("content_hash") or hashlib.md5((a.get("body") or "").encode()).hexdigest()
        parts.append(f"{a.get('slug', '')}:{h}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _last_run_fingerprint(module: str) -> str | None:
    """Read the corpus fingerprint from the last successful run of a module."""
    if not RUNS_LOG.exists():
        return None
    last = None
    for line in RUNS_LOG.read_text().splitlines():
        try:
            entry = json.loads(line)
            if entry.get("module") == module:
                last = entry
        except json.JSONDecodeError:
            continue
    return last.get("corpus_fingerprint") if last else None


def _log_run(module: str, fingerprint: str) -> None:
    """Log a completed non-psychoprofile run (psychoprofile logs itself)."""
    from datetime import datetime, timezone
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "module": module,
        "corpus_fingerprint": fingerprint,
    }
    with open(RUNS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``python -m analysis`` argument parser."""
    parser = argparse.ArgumentParser(
        description="Analyze Dr. George Calhoun's Forbes article corpus"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["all"],
        metavar="{all," + ",".join(ALL_MODULES) + "}",
        help="Which analysis modules to run (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Estimate costs without calling APIs")
    parser.add_argument("--local", action="store_true",
                        help="(deprecated, no-op — local conductor routing is now the default)")
    parser.add_argument("--remote", action="store_true",
                        help="Route psychoprofile LLM calls through conductor T3 remote tier")
    parser.add_argument("--force", action="store_true",
                        help="Re-run all modules even if corpus is unchanged")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        log.setLevel("DEBUG")

    if args.local and args.remote:
        log.error("cannot specify both --local and --remote")
        sys.exit(1)

    router = "conductor_remote" if args.remote else "conductor_local"

    modules = args.modules
    invalid = [m for m in modules if m not in {"all", *ALL_MODULES}]
    if invalid:
        parser.error(
            f"argument modules: invalid choice: {invalid[0]!r} "
            f"(choose from 'all', {', '.join(repr(m) for m in ALL_MODULES)})"
        )
    if "all" in modules:
        modules = ALL_MODULES

    articles = load_articles()
    log.info("Loaded %d articles for analysis", len(articles))

    fingerprint = _corpus_fingerprint(articles)

    def _should_run(module: str) -> bool:
        if args.force:
            return True
        last = _last_run_fingerprint(module)
        if last == fingerprint:
            log.info("[skip] %s: corpus unchanged since last run (use --force to override)", module)
            return False
        return True

    if "linguistic" in modules:
        log.info("=== LINGUISTIC FINGERPRINT ===")
        if _should_run("linguistic"):
            from .linguistic import run as run_linguistic
            run_linguistic(articles)
            _log_run("linguistic", fingerprint)

    if "themes" in modules:
        log.info("=== THEME ANALYSIS ===")
        if _should_run("themes"):
            from .themes import run as run_themes
            run_themes(articles)
            _log_run("themes", fingerprint)

    if "entities" in modules:
        log.info("=== NAMED ENTITY EXTRACTION ===")
        if _should_run("entities"):
            from .entities import run as run_entities
            run_entities(articles)
            _log_run("entities", fingerprint)

    if "psychoprofile" in modules:
        log.info("=== PSYCHOANALYTIC PROFILE ===")
        if _should_run("psychoprofile"):
            from .psychoprofile import run as run_psychoprofile
            run_psychoprofile(articles, dry_run=args.dry_run, router=router,
                              corpus_fingerprint=fingerprint)

    if "semantic_search" in modules:
        log.info("=== SEMANTIC SEARCH INDEX ===")
        if _should_run("semantic_search"):
            from .semantic_search import run as run_semantic_search
            run_semantic_search(articles)
            _log_run("semantic_search", fingerprint)

    if "predictions" in modules:
        log.info("=== TRACK RECORD — PREDICTION EXTRACTION ===")
        if _should_run("predictions"):
            from .predictions import run as run_predictions
            run_predictions(articles, router=router)
            _log_run("predictions", fingerprint)

    log.info("Analysis complete.")


if __name__ == "__main__":
    main()
