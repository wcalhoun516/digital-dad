"""Every ``make <target>`` the project tells a human to run must actually exist.

The Reading Room shipped with its regeneration command documented in the README, in the
module docstring, and — most visibly — in the dashboard's own empty state ("Run
``make reading-room`` then ``make dashboard``"), while no such target was ever added to the
Makefile. Following the instruction printed on the page failed with
``No rule to make target 'reading-room'``.

These tests pin the docs and the Makefile together in both directions.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"

# Files that instruct a human to run a make target.
DOC_SOURCES = (
    "README.md",
    "CLAUDE.md",
    "dashboard/template.html",
    "viz/build_dashboard.py",
    "analysis/reading_room.py",
    ".gitignore",
)

# `[ \t]+`, not `\s+`: a target always sits on the same line as its `make`, and spanning
# newlines would stitch two adjacent code spans (`make` + `analysis/voice_eval.py`) together.
_MAKE_REF = re.compile(r"\bmake[ \t]+([a-z][a-z0-9-]*)")

# A Makefile rule line: `target:` / `target: deps` (not a variable assignment).
_TARGET = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*:(?!=)", re.MULTILINE)

# Only *code* is an instruction to run something. Prose that happens to contain the word
# "make" ("columnists make predictions", "words that make his writing distinctively his")
# is not, so references are read from fenced blocks, backtick spans and <code> tags only.
_CODE_SPANS = (
    re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL),  # markdown fenced block
    re.compile(r"``(.+?)``", re.DOTALL),  # rst-style literal in a docstring
    re.compile(r"`([^`\n]+)`"),  # inline code span
    re.compile(r"<code>(.*?)</code>", re.DOTALL),  # html
)


def makefile_targets() -> set[str]:
    return set(_TARGET.findall(MAKEFILE.read_text()))


def _code_only(text: str) -> str:
    return "\n".join(m for pattern in _CODE_SPANS for m in pattern.findall(text))


def documented_targets() -> dict[str, set[str]]:
    """Map ``target -> {files that tell a human to run it}``, reading code contexts only."""
    found: dict[str, set[str]] = {}
    for rel in DOC_SOURCES:
        path = ROOT / rel
        if not path.exists():
            continue
        for name in _MAKE_REF.findall(_code_only(path.read_text())):
            found.setdefault(name, set()).add(rel)
    return found


def test_makefile_exposes_a_reading_room_target():
    """The Reading Room is git-ignored, so regenerating it is the only way to populate it."""
    assert "reading-room" in makefile_targets()


def test_the_reading_room_target_runs_the_reading_room_module():
    body = MAKEFILE.read_text()
    recipe = body.split("reading-room:", 1)[1].split("\n\n", 1)[0]
    assert "analysis.reading_room" in recipe


def test_the_reading_room_target_forwards_args():
    """The README documents `make reading-room ARGS="--dry-run"` and `ARGS="--limit 20"`."""
    body = MAKEFILE.read_text()
    recipe = body.split("reading-room:", 1)[1].split("\n\n", 1)[0]
    assert "$(ARGS)" in recipe


@pytest.mark.parametrize("target", sorted(documented_targets()))
def test_every_documented_make_target_exists(target):
    where = ", ".join(sorted(documented_targets()[target]))
    assert target in makefile_targets(), (
        f"`make {target}` is documented in {where} but is not a Makefile target"
    )
