"""Tests for analysis/utils.py structured-logging setup (roadmap #7).

Mirrors the scraper's `setup_logging` house pattern: a single named logger with
one StreamHandler, idempotent across calls, with a configurable level.
"""

import logging

from analysis.utils import setup_logging


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
