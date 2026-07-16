"""Characterization tests for the corpus-fingerprint helper in analysis/__main__.py."""

import hashlib

from analysis.__main__ import _corpus_fingerprint, build_parser


class TestVerboseFlag:
    def test_verbose_long_flag_sets_true(self):
        assert build_parser().parse_args(["--verbose"]).verbose is True

    def test_verbose_short_flag_sets_true(self):
        assert build_parser().parse_args(["-v"]).verbose is True

    def test_verbose_defaults_false(self):
        assert build_parser().parse_args([]).verbose is False


class TestCorpusFingerprint:
    def test_deterministic(self):
        articles = [{"slug": "a", "content_hash": "h1"}, {"slug": "b", "content_hash": "h2"}]
        assert _corpus_fingerprint(articles) == _corpus_fingerprint(articles)

    def test_order_independent(self):
        a = {"slug": "a", "content_hash": "h1"}
        b = {"slug": "b", "content_hash": "h2"}
        assert _corpus_fingerprint([a, b]) == _corpus_fingerprint([b, a])

    def test_content_hash_change_changes_fingerprint(self):
        before = [{"slug": "a", "content_hash": "h1"}]
        after = [{"slug": "a", "content_hash": "h2"}]
        assert _corpus_fingerprint(before) != _corpus_fingerprint(after)

    def test_falls_back_to_body_hash_when_no_content_hash(self):
        body = "the fed is wrong"
        no_hash = [{"slug": "a", "body": body}]
        with_hash = [{"slug": "a", "content_hash": hashlib.md5(body.encode()).hexdigest()}]
        assert _corpus_fingerprint(no_hash) == _corpus_fingerprint(with_hash)

    def test_body_change_changes_fingerprint(self):
        before = [{"slug": "a", "body": "first"}]
        after = [{"slug": "a", "body": "second"}]
        assert _corpus_fingerprint(before) != _corpus_fingerprint(after)
