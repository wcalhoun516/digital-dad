"""Guard: docs/architecture.md keeps pace with the modules it claims to map.

docs/INDEX.md sends every new session to architecture.md as "the repo map ... read this
before touching any module". Nothing enforced that, so modules landed without an entry.
"""

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
README = REPO_ROOT / "README.md"

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


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def console_routes() -> tuple[str, ...]:
    """The console route table, read from the server rather than restated here."""
    spec = importlib.util.spec_from_file_location(
        "_serve_dashboard_for_docs", REPO_ROOT / "bin" / "serve_dashboard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.CONSOLE_ROUTES)


def is_route_documented(doc: str, route: str) -> bool:
    """True when the doc names the route exactly, inside a code span or fenced block.

    The negative lookahead stops `/console/api/job/log` from vacuously documenting
    `/console/api/job` — a reader who needs the shorter one learns nothing from the longer.
    """
    pattern = re.escape(route) + r"(?![\w/-])"
    return any(re.search(pattern, literal) for literal in code_literals(doc))


# --- `make <target>` references -------------------------------------------------------
# Files that tell a human (or the family, from the dashboard) to run a make target.
COMMAND_SOURCES = [
    "README.md",
    "docs/architecture.md",
    "docs/INDEX.md",
    "docs/decisions.md",
    "docs/runbooks/adding-an-analysis-module.md",
    "dashboard/template.html",
]

MAKE_TARGET_RE = re.compile(r"^([a-zA-Z][\w-]*)\s*:(?!=)", re.MULTILINE)
MAKE_CALL_RE = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)")


def makefile_targets() -> set[str]:
    return set(MAKE_TARGET_RE.findall((REPO_ROOT / "Makefile").read_text(encoding="utf-8")))


def code_literals(text: str) -> list[str]:
    """Code spans, fenced blocks and <code> elements — where commands are written.

    Prose is deliberately excluded so English ("make sure the conductor is up") can't be
    mistaken for a target reference.
    """
    return (
        re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
        + re.findall(r"`([^`\n]+)`", text)
        + re.findall(r"<code>(.*?)</code>", text, re.DOTALL)
    )


def referenced_make_targets(text: str) -> set[str]:
    return {t for literal in code_literals(text) for t in MAKE_CALL_RE.findall(literal)}


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


class TestMakeTargetsExist:
    @pytest.mark.parametrize("source", COMMAND_SOURCES)
    def test_referenced_make_targets_exist(self, source):
        text = (REPO_ROOT / source).read_text(encoding="utf-8")
        missing = sorted(referenced_make_targets(text) - makefile_targets())
        assert not missing, (
            f"{source} tells the reader to run make target(s) that do not exist: "
            f"{', '.join(missing)}"
        )

    def test_discovery_finds_real_targets(self):
        targets = makefile_targets()
        assert {"verify", "dashboard", "analyze"} <= targets


class TestReferencedMakeTargets:
    def test_finds_target_in_code_span(self):
        assert referenced_make_targets("run `make dashboard` now") == {"dashboard"}

    def test_finds_target_in_fenced_block(self):
        assert referenced_make_targets("```bash\nmake analyze\n```") == {"analyze"}

    def test_finds_target_in_html_code_element(self):
        assert referenced_make_targets("<code>make reading-room</code>") == {"reading-room"}

    def test_ignores_prose_outside_code(self):
        assert referenced_make_targets("make sure the conductor is up") == set()

    def test_ignores_make_with_arguments_after_the_target(self):
        assert referenced_make_targets('`make anthology ARGS="--year 2024"`') == {"anthology"}


class TestConsoleRouteDocCoverage:
    """Guard: the README documents every console route the server actually answers.

    The console is a write surface reached by a human typing a URL, not by another program
    reading a schema — so the route list in `bin/serve_dashboard.py` and the route list a
    reader can find are the same list, or the second one is wrong. Read from
    `CONSOLE_ROUTES` rather than restated here, so a route added by a later step of plan
    0011 joins this test on its own.
    """

    @pytest.mark.parametrize("route", console_routes())
    def test_route_is_documented_in_readme(self, readme, route):
        assert is_route_documented(readme, route), (
            f"{route} is served by bin/serve_dashboard.py but appears nowhere in README.md. "
            f"The console is operated by hand; an undocumented route is an unreachable one."
        )

    def test_discovery_finds_the_real_route_table(self):
        routes = console_routes()
        assert "/console" in routes
        assert all(r.startswith("/console") for r in routes)


class TestIsRouteDocumented:
    def test_accepts_route_in_code_span(self):
        assert is_route_documented("`GET /console/api/queue` lists items", "/console/api/queue")

    def test_accepts_route_in_fenced_block(self):
        assert is_route_documented("```\ncurl /console/api/queue\n```", "/console/api/queue")

    def test_rejects_unbackticked_mention(self):
        assert not is_route_documented("visit /console/api/queue in a browser",
                                       "/console/api/queue")

    def test_rejects_absent_route(self):
        assert not is_route_documented("`/console/api/queue`", "/console/api/upload")

    def test_does_not_credit_a_longer_route_for_its_prefix(self):
        """`/console/api/job/log` documented must not silently document `/console/api/job`."""
        assert not is_route_documented("`GET /console/api/job/log`", "/console/api/job")

    def test_prefix_route_is_documented_when_named_exactly(self):
        assert is_route_documented("`GET /console/api/job/log` and `GET /console/api/job`",
                                   "/console/api/job")


class TestIsDocumented:
    def test_accepts_bare_filename_code_span(self):
        assert is_documented("`themes.py` clusters articles.", "analysis", "themes.py")

    def test_accepts_package_qualified_filename(self):
        assert is_documented("see `analysis/utils.py`", "analysis", "utils.py")

    def test_accepts_filename_inside_a_longer_code_span(self):
        doc = "`python -m analysis.themes` ... `run themes.py`"
        assert is_documented(doc, "analysis", "themes.py")

    def test_rejects_artifact_mention_only(self):
        assert not is_documented("emits `reading_room.json`", "analysis", "reading_room.py")

    def test_rejects_unbackticked_mention(self):
        assert not is_documented("themes.py clusters articles.", "analysis", "themes.py")

    def test_rejects_absent_module(self):
        assert not is_documented("`themes.py`", "analysis", "delivery.py")

    def test_does_not_match_a_different_module_sharing_a_suffix(self):
        assert not is_documented("`entity_graph.py`", "analysis", "graph.py")
