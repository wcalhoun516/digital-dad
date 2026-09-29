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
  python -m analysis entity_graph       # rebuild one derived view (see DERIVED_MODULES)
"""

import argparse
import hashlib
import json
import sys

from .utils import DATA_DIR, load_articles, log

ANALYSIS_DIR = DATA_DIR / "analysis"
RUNS_LOG = ANALYSIS_DIR / "runs.jsonl"
PRIMARY_MODULES = ["linguistic", "themes", "entities", "psychoprofile", "semantic_search",
                   "predictions", "corpus_composition"]

# Derived builders (roadmap #47): pure/offline views over the primary modules' outputs, each
# mapped to the upstream files (in ANALYSIS_DIR) it reads besides the corpus. They run after
# every primary module and are gated on a fingerprint of *those inputs*, not the corpus alone:
# themes.json and entities.json get regenerated with the corpus unchanged (a --force
# re-cluster, boilerplate pruning), and a corpus-only gate would leave every tab downstream
# of them stale. Before this they ran only by hand, and sat 3–7 weeks behind their neighbours.
DERIVED_MODULES = {
    "intellectual_arc": ("themes.json",),
    "reading_room": ("themes.json",),
    "calhoun_isms": ("themes.json",),
    "entity_graph": ("entities.json",),
    "entity_stance": ("entities.json",),
    "contradictions": ("entities.json",),
}
ALL_MODULES = PRIMARY_MODULES + list(DERIVED_MODULES)


def _corpus_fingerprint(articles: list[dict]) -> str:
    """Return an MD5 of all article slugs+content_hashes to detect corpus changes."""
    parts = []
    for a in sorted(articles, key=lambda x: x.get("slug", "")):
        # Use existing content_hash if present, else hash body
        h = a.get("content_hash") or hashlib.md5((a.get("body") or "").encode()).hexdigest()
        parts.append(f"{a.get('slug', '')}:{h}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _last_run_fingerprint(module: str, key: str = "corpus_fingerprint") -> str | None:
    """Read a fingerprint (the corpus one by default) from a module's last successful run."""
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
    return last.get(key) if last else None


def _log_run(module: str, fingerprint: str, **extra: str) -> None:
    """Log a completed non-psychoprofile run (psychoprofile logs itself)."""
    from datetime import datetime, timezone
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "module": module,
        "corpus_fingerprint": fingerprint,
        **extra,
    }
    with open(RUNS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _inputs_fingerprint(corpus_fingerprint: str, upstream: tuple[str, ...]) -> str:
    """MD5 over the corpus fingerprint plus the bytes of each upstream file a builder reads.

    Raises FileNotFoundError when an upstream file is missing: the builder cannot run, and
    that is a failure to report, not a reason to skip quietly.
    """
    h = hashlib.md5(corpus_fingerprint.encode())
    for name in upstream:
        h.update(f"|{name}:".encode())
        h.update((ANALYSIS_DIR / name).read_bytes())
    return h.hexdigest()


def _build_derived(name: str, articles: list[dict]) -> None:
    """Run one derived builder with its CLI defaults, writing its output file."""
    if name == "intellectual_arc":
        from .intellectual_arc import run
        run()
    elif name == "reading_room":
        from .reading_room import run
        run()
    elif name == "calhoun_isms":
        from .calhoun_isms import run
        run(articles)
    elif name == "entity_graph":
        from .entity_graph import run
        run()
    elif name == "entity_stance":
        from .entity_stance import run
        run(articles)
    elif name == "contradictions":
        from .contradictions import run
        run(articles)
    else:
        raise KeyError(f"no derived builder named {name!r}")


def run_derived(articles: list[dict], corpus_fingerprint: str, modules: list[str], *,
                force: bool = False, dry_run: bool = False, build=None) -> list[str]:
    """Run the requested derived builders whose inputs changed; return the names that failed.

    A crash in one builder is logged and does not stop the rest; it is not recorded in
    runs.jsonl, so the next run retries it. ``build`` is injectable for tests.
    """
    build = build or _build_derived
    failed: list[str] = []
    for name, upstream in DERIVED_MODULES.items():
        if name not in modules:
            continue
        log.info("=== DERIVED — %s ===", name)
        if dry_run:
            log.info("[skip] %s: --dry-run (derived builders write files)", name)
            continue
        try:
            inputs = _inputs_fingerprint(corpus_fingerprint, upstream)
            if not force and _last_run_fingerprint(name, "inputs_fingerprint") == inputs:
                log.info("[skip] %s: inputs unchanged since last run (use --force to override)",
                         name)
                continue
            build(name, articles)
        except Exception:
            log.exception("%s failed; the other builders carry on", name)
            failed.append(name)
            continue
        _log_run(name, corpus_fingerprint, inputs_fingerprint=inputs)
    return failed


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

    # Deliberately NOT behind _should_run. The fingerprint hashes what load_articles returns,
    # which skips manifest entries naming no raw file — exactly what an accepted ingest item
    # is. So the arrival of a book leaves the fingerprint unchanged, and gating this module on
    # it would pin the panel at "100% article" through the very change it exists to report.
    # It reads only the manifest, so running it every time costs nothing.
    if "corpus_composition" in modules:
        log.info("=== CORPUS COMPOSITION — what the corpus is made of ===")
        from .corpus_composition import run as run_corpus_composition
        run_corpus_composition(articles)

    failed = run_derived(articles, fingerprint, modules, force=args.force, dry_run=args.dry_run)
    if failed:
        log.error("Analysis finished with failed derived builders: %s", ", ".join(failed))
        sys.exit(1)

    log.info("Analysis complete.")


if __name__ == "__main__":
    main()
