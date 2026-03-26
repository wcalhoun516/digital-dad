"""CLI entry point: python -m analysis

Runs all analysis modules or individual ones.
"""

import argparse
import sys

from .utils import load_articles


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Dr. George Calhoun's Forbes article corpus"
    )
    parser.add_argument(
        "modules",
        nargs="*",
        default=["all"],
        choices=["all", "linguistic", "themes", "psychoprofile"],
        help="Which analysis modules to run (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Estimate costs without calling APIs")
    args = parser.parse_args()

    modules = args.modules
    if "all" in modules:
        modules = ["linguistic", "themes", "psychoprofile"]

    articles = load_articles()
    print(f"Loaded {len(articles)} articles for analysis\n")

    if "linguistic" in modules:
        print("=" * 50)
        print("LINGUISTIC FINGERPRINT")
        print("=" * 50)
        from .linguistic import run as run_linguistic
        run_linguistic(articles)
        print()

    if "themes" in modules:
        print("=" * 50)
        print("THEME ANALYSIS")
        print("=" * 50)
        from .themes import run as run_themes
        run_themes(articles)
        print()

    if "psychoprofile" in modules:
        print("=" * 50)
        print("PSYCHOANALYTIC PROFILE")
        print("=" * 50)
        from .psychoprofile import run as run_psychoprofile
        run_psychoprofile(articles, dry_run=args.dry_run)
        print()

    print("Analysis complete.")


if __name__ == "__main__":
    main()
