"""Guards on the ruff gate's *scope* (roadmap #1-3 cleanup).

`make lint` used to check only `tests/`, so every line of production code was unlinted.
These tests pin the widened scope: the gate must cover each source package, the pre-commit
hook must mirror `make lint`, and `tests/` must not lose any rule in the process.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
PRECOMMIT = ROOT / ".pre-commit-config.yaml"
PYPROJECT = ROOT / "pyproject.toml"

# Every top-level directory holding Python we ship. `bin/` is the weekly-cron scripts,
# `tools/` the pre-commit helpers; both are import-free of each other but still ours.
SOURCE_PACKAGES = ("analysis", "scraper", "viz", "training", "tools", "bin", "tests")


def _lint_paths():
    m = re.search(r"^LINT_PATHS\s*:?=\s*(.+)$", MAKEFILE.read_text(encoding="utf-8"), re.M)
    assert m, "Makefile no longer defines LINT_PATHS"
    return m.group(1).split()


def _precommit_ruff_files_pattern():
    text = PRECOMMIT.read_text(encoding="utf-8")
    block = text.split("id: ruff-check", 1)
    assert len(block) == 2, "no ruff-check hook in .pre-commit-config.yaml"
    m = re.search(r"^\s*files:\s*(\S+)\s*$", block[1], re.M)
    assert m, "the ruff-check hook no longer declares a files: pattern"
    return m.group(1)


def test_lint_paths_cover_every_source_package():
    paths = _lint_paths()
    missing = [p for p in SOURCE_PACKAGES if (ROOT / p).is_dir() and p not in paths]
    assert not missing, f"LINT_PATHS does not cover: {missing}"


def test_lint_paths_all_exist():
    for p in _lint_paths():
        assert (ROOT / p).is_dir(), f"LINT_PATHS names a missing directory: {p}"


def test_the_gate_is_green():
    """`make lint` over the widened scope must actually pass."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *_lint_paths()],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_precommit_hook_mirrors_make_lint():
    pattern = re.compile(_precommit_ruff_files_pattern())
    for pkg in _lint_paths():
        assert pattern.match(f"{pkg}/example.py"), f"pre-commit hook skips {pkg}/"


def test_tests_dir_keeps_every_rule():
    """Widening the scope must not buy source coverage by weakening `tests/`."""
    text = PYPROJECT.read_text(encoding="utf-8")
    section = text.split("[tool.ruff.lint.per-file-ignores]", 1)
    if len(section) == 1:
        return
    for line in section[1].splitlines():
        if line.startswith("["):
            break
        key = re.match(r'^\s*"([^"]+)"\s*=', line)
        assert not (key and key.group(1).startswith("tests")), f"tests/ ignores a rule: {line}"
