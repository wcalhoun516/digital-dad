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


# --- Derived builders (roadmap #47) -------------------------------------------------------
#
# Six builders read the primary modules' outputs rather than the corpus alone. They used to
# run only by hand, so their tabs sat 3–7 weeks stale beside tabs the weekly cron refreshed.

import json  # noqa: E402

import pytest  # noqa: E402

import analysis.__main__ as pipeline  # noqa: E402

DERIVED = ["intellectual_arc", "reading_room", "calhoun_isms",
           "entity_graph", "entity_stance", "contradictions"]

# Which primary module writes each upstream file a derived builder reads.
PRODUCER = {"themes.json": "themes", "entities.json": "entities"}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A private analysis dir + runs log, with both upstream files present."""
    monkeypatch.setattr(pipeline, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "RUNS_LOG", tmp_path / "runs.jsonl")
    (tmp_path / "themes.json").write_text('{"clusters": 1}')
    (tmp_path / "entities.json").write_text('{"people": []}')
    return tmp_path


class Recorder:
    """Stands in for the real builders: records the order it was asked to build in."""

    def __init__(self, fail=()):
        self.built: list[str] = []
        self.fail = set(fail)

    def __call__(self, name, articles):
        if name in self.fail:
            raise RuntimeError(f"{name} blew up")
        self.built.append(name)


ARTICLES = [{"slug": "a", "content_hash": "h1"}]
FP = _corpus_fingerprint(ARTICLES)


class TestDerivedRegistry:
    def test_all_six_are_pipeline_modules(self):
        assert set(DERIVED) <= set(pipeline.ALL_MODULES)
        assert set(pipeline.DERIVED_MODULES) == set(DERIVED)

    @pytest.mark.parametrize("name", DERIVED)
    def test_each_runs_after_the_modules_it_reads(self, name):
        for upstream in pipeline.DERIVED_MODULES[name]:
            producer = PRODUCER[upstream]
            assert pipeline.ALL_MODULES.index(producer) < pipeline.ALL_MODULES.index(name)

    def test_cli_accepts_a_derived_module_by_name(self):
        assert build_parser().parse_args(["entity_graph"]).modules == ["entity_graph"]

    @pytest.mark.parametrize("name", DERIVED)
    def test_every_registered_builder_dispatches_to_its_modules_run(self, name, monkeypatch):
        import importlib

        module = importlib.import_module(f"analysis.{name}")
        calls = []
        monkeypatch.setattr(module, "run", lambda *a, **k: calls.append((a, k)))
        pipeline._build_derived(name, ARTICLES)
        assert len(calls) == 1


class TestRunDerived:
    def test_first_run_builds_every_requested_module_in_order(self, workspace):
        build = Recorder()
        failed = pipeline.run_derived(ARTICLES, FP, pipeline.ALL_MODULES, build=build)
        assert failed == []
        assert build.built == [m for m in pipeline.ALL_MODULES if m in DERIVED]

    def test_only_requested_modules_run(self, workspace):
        build = Recorder()
        pipeline.run_derived(ARTICLES, FP, ["themes", "entity_graph"], build=build)
        assert build.built == ["entity_graph"]

    def test_unchanged_inputs_skip_everything(self, workspace):
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=Recorder())
        again = Recorder()
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=again)
        assert again.built == []

    def test_regenerated_upstream_reruns_only_its_dependents(self, workspace):
        """The corpus fingerprint did not move, but themes.json did — exactly what a
        `--force` re-cluster or boilerplate pruning does. A corpus-only gate misses this."""
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=Recorder())
        (workspace / "themes.json").write_text('{"clusters": 2}')
        again = Recorder()
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=again)
        assert sorted(again.built) == sorted(
            n for n in DERIVED if "themes.json" in pipeline.DERIVED_MODULES[n]
        )
        assert again.built  # the themes dependents did re-run

    def test_corpus_change_reruns_everything(self, workspace):
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=Recorder())
        again = Recorder()
        pipeline.run_derived(ARTICLES, "a-new-corpus", DERIVED, build=again)
        assert sorted(again.built) == sorted(DERIVED)

    def test_force_reruns_unchanged_modules(self, workspace):
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=Recorder())
        again = Recorder()
        pipeline.run_derived(ARTICLES, FP, DERIVED, force=True, build=again)
        assert sorted(again.built) == sorted(DERIVED)

    def test_a_crash_is_isolated_reported_and_retried(self, workspace):
        build = Recorder(fail={"entity_graph"})
        failed = pipeline.run_derived(ARTICLES, FP, DERIVED, build=build)
        assert failed == ["entity_graph"]
        assert sorted(build.built) == sorted(n for n in DERIVED if n != "entity_graph")
        # Not logged as done, so the next run tries it again.
        again = Recorder()
        pipeline.run_derived(ARTICLES, FP, DERIVED, build=again)
        assert again.built == ["entity_graph"]

    def test_missing_upstream_is_a_failure_not_a_silent_skip(self, workspace):
        (workspace / "entities.json").unlink()
        build = Recorder()
        failed = pipeline.run_derived(ARTICLES, FP, DERIVED, build=build)
        assert sorted(failed) == sorted(
            n for n in DERIVED if "entities.json" in pipeline.DERIVED_MODULES[n]
        )
        assert sorted(build.built) == sorted(
            n for n in DERIVED if "entities.json" not in pipeline.DERIVED_MODULES[n]
        )

    def test_dry_run_builds_nothing_and_logs_nothing(self, workspace):
        build = Recorder()
        assert pipeline.run_derived(ARTICLES, FP, DERIVED, dry_run=True, build=build) == []
        assert build.built == []
        assert not (workspace / "runs.jsonl").exists()

    def test_a_logged_run_records_the_inputs_fingerprint(self, workspace):
        pipeline.run_derived(ARTICLES, FP, ["intellectual_arc"], build=Recorder())
        entry = json.loads((workspace / "runs.jsonl").read_text().splitlines()[-1])
        assert entry["module"] == "intellectual_arc"
        assert entry["corpus_fingerprint"] == FP
        assert entry["inputs_fingerprint"] and entry["inputs_fingerprint"] != FP


class TestMainExitStatus:
    def test_a_failed_derived_builder_fails_the_run(self, workspace, monkeypatch):
        """The weekly cron records each step's exit code — a crash must not read as `ok`."""
        monkeypatch.setattr(pipeline, "load_articles", lambda: ARTICLES)
        monkeypatch.setattr(pipeline, "_build_derived", Recorder(fail={"entity_graph"}))
        monkeypatch.setattr("sys.argv", ["analysis", "entity_graph"])
        with pytest.raises(SystemExit) as exc:
            pipeline.main()
        assert exc.value.code == 1

    def test_a_clean_run_returns_normally(self, workspace, monkeypatch):
        monkeypatch.setattr(pipeline, "load_articles", lambda: ARTICLES)
        monkeypatch.setattr(pipeline, "_build_derived", Recorder())
        monkeypatch.setattr("sys.argv", ["analysis", "entity_graph"])
        pipeline.main()
