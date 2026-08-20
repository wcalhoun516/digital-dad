"""Guard: docs/architecture.md keeps pace with the modules it claims to map.

docs/INDEX.md sends every new session to architecture.md as "the repo map ... read this
before touching any module". Nothing enforced that, so modules landed without an entry.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"

# Dunder files are packaging/CLI plumbing, documented as a package rather than per-file.
EXCLUDED = {"__init__.py", "__main__.py"}


def package_modules(package: str) -> list[str]:
    """Every documentable module filename in a top-level package, sorted."""
    return sorted(
        p.name for p in (REPO_ROOT / package).glob("*.py") if p.name not in EXCLUDED
    )


def is_documented(doc: str, package: str, filename: str) -> bool:
    """True when the doc anchors the module by filename in a code span.

    Requires `foo.py` or `analysis/foo.py` — not a passing mention of the artifact it
    writes (`foo.json`), which would let an undescribed module pass vacuously.
    """
    pattern = rf"`(?:[^`\n]*(?:[^\w./]|{re.escape(package)}/))?{re.escape(filename)}`"
    return re.search(pattern, doc) is not None


@pytest.fixture(scope="module")
def architecture_doc() -> str:
    return ARCHITECTURE.read_text(encoding="utf-8")


class TestArchitectureDocCoverage:
    @pytest.mark.parametrize("filename", package_modules("analysis"))
    def test_analysis_module_is_documented(self, architecture_doc, filename):
        assert is_documented(architecture_doc, "analysis", filename), (
            f"analysis/{filename} has no entry in docs/architecture.md. "
            f"Add one (see the runbook) or the repo map goes stale."
        )

    def test_discovery_finds_the_real_package(self):
        modules = package_modules("analysis")
        assert "themes.py" in modules
        assert "__init__.py" not in modules


class TestIsDocumented:
    def test_accepts_bare_filename_code_span(self):
        assert is_documented("`themes.py` clusters articles.", "analysis", "themes.py")

    def test_accepts_package_qualified_filename(self):
        assert is_documented("see `analysis/utils.py`", "analysis", "utils.py")

    def test_accepts_filename_inside_a_longer_code_span(self):
        assert is_documented("`python -m analysis.themes`... `run themes.py`", "analysis", "themes.py")

    def test_rejects_artifact_mention_only(self):
        assert not is_documented("emits `reading_room.json`", "analysis", "reading_room.py")

    def test_rejects_unbackticked_mention(self):
        assert not is_documented("themes.py clusters articles.", "analysis", "themes.py")

    def test_rejects_absent_module(self):
        assert not is_documented("`themes.py`", "analysis", "delivery.py")

    def test_does_not_match_a_different_module_sharing_a_suffix(self):
        assert not is_documented("`entity_graph.py`", "analysis", "graph.py")
