"""Tests for analysis structured logging (roadmap #7).

Two halves: `analysis/utils.py`'s `setup_logging` helper, and its *adoption* by the
modules `python -m analysis` runs — a helper nothing calls leaves `--verbose` a no-op.
"""

import ast
import logging
from pathlib import Path

import pytest

from analysis import psychoprofile, semantic_search
from analysis.utils import setup_logging

REPO_ROOT = Path(__file__).resolve().parent.parent

# The modules `python -m analysis` runs (ALL_MODULES in analysis/__main__.py).
PIPELINE_MODULES = [
    "linguistic",
    "themes",
    "entities",
    "psychoprofile",
    "semantic_search",
    "predictions",
]

# Functions whose stdout *is* the product rather than a progress diagnostic:
# a user typing `python -m analysis.semantic_search "query"` wants the results on
# stdout so they can pipe them. Everything else in these modules is a diagnostic.
STDOUT_IS_THE_PRODUCT = {
    "semantic_search": {"_cli"},
}


class TestSetupLogging:
    def test_returns_named_analysis_logger(self):
        logger = setup_logging()
        assert logger.name == "digital-dad.analysis"

    def test_attaches_stream_handler_with_formatter(self):
        logger = setup_logging()
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert stream_handlers, "expected at least one StreamHandler"
        assert stream_handlers[0].formatter is not None

    def test_is_idempotent_no_duplicate_handlers(self):
        first = setup_logging()
        count = len(first.handlers)
        second = setup_logging()
        assert first is second
        assert len(second.handlers) == count

    def test_respects_level_argument(self):
        logger = setup_logging("DEBUG")
        assert logger.level == logging.DEBUG

    def test_level_argument_is_case_insensitive(self):
        logger = setup_logging("debug")
        assert logger.level == logging.DEBUG

    def test_invalid_level_falls_back_to_info(self):
        setup_logging("DEBUG")  # ensure level isn't already INFO
        logger = setup_logging("nonsense-level")
        assert logger.level == logging.INFO


def _print_calls(module: str) -> list[tuple[str, int]]:
    """Return (enclosing_function, lineno) for every `print(...)` in a pipeline module.

    Calls inside a `STDOUT_IS_THE_PRODUCT` function are excluded.
    """
    source = (REPO_ROOT / "analysis" / f"{module}.py").read_text()
    tree = ast.parse(source)

    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                # Innermost wins: walk order visits outer defs first, so only
                # record a line the first time an inner function claims it.
                if isinstance(child, ast.Call) and getattr(child.func, "id", None) == "print":
                    enclosing.setdefault(child.lineno, node.name)

    exempt = STDOUT_IS_THE_PRODUCT.get(module, set())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            func = enclosing.get(node.lineno, "<module>")
            if func not in exempt:
                found.append((func, node.lineno))
    return sorted(found, key=lambda pair: pair[1])


class TestPipelineModulesUseTheLogger:
    """The six modules `python -m analysis` runs must route diagnostics through the
    shared logger, so `--verbose` and the weekly cron's log file see all of them."""

    @pytest.mark.parametrize("module", PIPELINE_MODULES)
    def test_no_diagnostic_print_calls(self, module):
        offenders = _print_calls(module)
        assert not offenders, (
            f"analysis/{module}.py writes diagnostics to stdout instead of the shared "
            f"'digital-dad.analysis' logger, so `python -m analysis --verbose` cannot "
            f"control them: "
            + ", ".join(f"{func}() line {line}" for func, line in offenders)
        )

    @pytest.mark.parametrize("module", PIPELINE_MODULES)
    def test_imports_the_shared_logger(self, module):
        tree = ast.parse((REPO_ROOT / "analysis" / f"{module}.py").read_text())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module in ("utils", "analysis.utils")
            for alias in node.names
        }
        assert "log" in imported, (
            f"analysis/{module}.py should import the shared `log` from .utils; "
            f"it imports {sorted(imported) or 'nothing'}"
        )


class TestLoggingIsWiredEndToEnd:
    """Structure isn't enough — prove a real call emits on the shared logger."""

    ARTICLES = [
        {
            "slug": "test-article",
            "title": "A Test Column",
            "date": "2024-01-01",
            "body": "The Federal Reserve moved rates again. " * 40,
        }
    ]

    def test_psychoprofile_dry_run_emits_on_the_shared_logger(self, caplog):
        with caplog.at_level(logging.INFO, logger="digital-dad.analysis"):
            psychoprofile.run(articles=self.ARTICLES, dry_run=True)

        records = [r for r in caplog.records if r.name == "digital-dad.analysis"]
        assert records, "psychoprofile.run() emitted nothing on 'digital-dad.analysis'"
        assert any("1 article" in r.getMessage() for r in records)
        assert any("Dry run" in r.getMessage() for r in records)

    def test_psychoprofile_dry_run_writes_nothing_to_stdout(self, capsys):
        psychoprofile.run(articles=self.ARTICLES, dry_run=True)
        assert capsys.readouterr().out == "", (
            "progress output belongs on the logger (stderr, levelled), not stdout"
        )


class TestVerboseIsMeaningful:
    """`--verbose` is documented as DEBUG-level logging. That only means something if
    the pipeline's chatty per-batch progress is actually emitted at DEBUG."""

    @pytest.mark.parametrize(
        "module, needle",
        [
            ("entities", "log.debug"),
            ("psychoprofile", "log.debug"),
            ("semantic_search", "log.debug"),
            ("predictions", "log.debug"),
        ],
    )
    def test_per_item_progress_is_debug_level(self, module, needle):
        source = (REPO_ROOT / "analysis" / f"{module}.py").read_text()
        assert needle in source, (
            f"analysis/{module}.py emits per-batch/per-article progress; that belongs at "
            f"DEBUG so `--verbose` has something to reveal and default runs stay readable"
        )

    def test_embedding_batches_are_hidden_at_info_and_shown_at_debug(
        self, tmp_path, monkeypatch, caplog
    ):
        """The payoff, exercised for real: drive the whole embed loop offline and
        confirm the per-batch lines only appear once the level drops to DEBUG."""
        npy, meta, export = tmp_path / "e.npy", tmp_path / "e_meta.json", tmp_path / "e.json"
        monkeypatch.setattr(semantic_search, "EMBEDDINGS_PATH", npy)
        monkeypatch.setattr(semantic_search, "METADATA_PATH", meta)
        monkeypatch.setattr(semantic_search, "DASHBOARD_EXPORT_PATH", export)
        monkeypatch.setattr(
            semantic_search, "_embed_batch", lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        )
        articles = [
            {"slug": f"a{i}", "title": f"T{i}", "date": "2024-01-01", "url": "u", "body": "text"}
            for i in range(4)
        ]

        def progress_lines(records):
            # Match the message only — a tmp_path can itself contain the word "batch".
            return [m for m in records if m.strip().startswith("batch")]

        with caplog.at_level(logging.INFO, logger="digital-dad.analysis"):
            semantic_search.build_embeddings(articles, batch_size=2)
        at_info = [r.getMessage() for r in caplog.records]

        # Second pass must re-embed, not hit the cache written by the first.
        caplog.clear()
        meta.unlink()
        with caplog.at_level(logging.DEBUG, logger="digital-dad.analysis"):
            semantic_search.build_embeddings(articles, batch_size=2)
        at_debug = [r.getMessage() for r in caplog.records]

        assert not progress_lines(at_info), (
            f"per-batch progress leaked into a default (INFO) run: {at_info}"
        )
        assert progress_lines(at_debug), (
            f"--verbose (DEBUG) revealed no per-batch progress: {at_debug}"
        )
