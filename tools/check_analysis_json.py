"""Validate that files parse as JSON — the pre-commit hook for `data/analysis/*.json`.

pre-commit passes the staged filenames as argv. Run standalone with no args to check the
committed `data/analysis/*.json` artifacts. Stdlib-only so it needs no install/network.
"""

import glob
import json
import sys
from collections.abc import Iterable

DEFAULT_GLOB = "data/analysis/*.json"


def find_invalid(paths: Iterable[str]) -> list[tuple[str, str]]:
    """Return (path, error) for each file that does not parse as JSON."""
    problems: list[tuple[str, str]] = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                json.load(fh)
        except (OSError, ValueError) as exc:
            problems.append((path, str(exc)))
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = args or sorted(glob.glob(DEFAULT_GLOB))
    problems = find_invalid(paths)
    for path, error in problems:
        print(f"{path}: invalid JSON: {error}")
    if problems:
        print(f"{len(problems)} file(s) failed JSON validation.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
