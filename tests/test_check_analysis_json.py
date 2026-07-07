"""Tests for the pre-commit JSON validity hook (roadmap #5)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_analysis_json
from tools.check_analysis_json import find_invalid, main

ROOT = Path(__file__).resolve().parent.parent


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_valid_object_file_has_no_error(tmp_path):
    p = _write(tmp_path / "obj.json", json.dumps({"a": 1, "b": [1, 2, 3]}))
    assert find_invalid([p]) == []


def test_valid_array_file_has_no_error(tmp_path):
    p = _write(tmp_path / "arr.json", json.dumps([1, 2, {"x": "y"}]))
    assert find_invalid([p]) == []


def test_syntax_error_is_reported(tmp_path):
    p = _write(tmp_path / "bad.json", '{"a": 1,}')  # trailing comma
    result = find_invalid([p])
    assert len(result) == 1
    assert result[0][0] == p
    assert result[0][1]  # a non-empty error message


def test_empty_file_is_reported(tmp_path):
    p = _write(tmp_path / "empty.json", "")
    result = find_invalid([p])
    assert len(result) == 1
    assert result[0][0] == p


def test_missing_file_is_reported(tmp_path):
    p = str(tmp_path / "nope.json")
    result = find_invalid([p])
    assert len(result) == 1
    assert result[0][0] == p


def test_mixed_batch_reports_only_invalid(tmp_path):
    good = _write(tmp_path / "good.json", "{}")
    bad = _write(tmp_path / "bad.json", "{not json}")
    result = find_invalid([good, bad])
    assert [r[0] for r in result] == [bad]


def test_main_returns_zero_when_all_valid(tmp_path, capsys):
    good = _write(tmp_path / "good.json", "[]")
    assert main([good]) == 0


def test_main_returns_one_and_prints_path_when_invalid(tmp_path, capsys):
    bad = _write(tmp_path / "bad.json", "oops")
    rc = main([bad])
    out = capsys.readouterr().out
    assert rc == 1
    assert bad in out


def test_unicode_content_is_valid(tmp_path):
    p = _write(tmp_path / "u.json", json.dumps({"name": "Señor Calhoun — €"}))
    assert find_invalid([p]) == []


def test_bare_scalar_is_valid_json(tmp_path):
    # A bare number/string is valid JSON per the spec; "validity" means it parses.
    p = _write(tmp_path / "scalar.json", "123")
    assert find_invalid([p]) == []


def test_main_with_no_args_scans_the_default_glob(tmp_path, monkeypatch):
    _write(tmp_path / "ok.json", "{}")
    _write(tmp_path / "broken.json", "{bad}")
    monkeypatch.setattr(check_analysis_json, "DEFAULT_GLOB", str(tmp_path / "*.json"))
    assert main([]) == 1


def test_cli_invocation_matches_hook_contract(tmp_path):
    # pre-commit calls `python -m tools.check_analysis_json <staged files...>` and gates on
    # the exit code — exercise that exact path via subprocess.
    good = _write(tmp_path / "good.json", "[]")
    bad = _write(tmp_path / "bad.json", "nope")

    ok = subprocess.run(
        [sys.executable, "-m", "tools.check_analysis_json", good],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0

    fail = subprocess.run(
        [sys.executable, "-m", "tools.check_analysis_json", bad],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert fail.returncode == 1
    assert bad in fail.stdout


def test_configured_hook_passes_on_the_real_corpus():
    # Integration: run the actual configured hook against every committed
    # data/analysis/*.json so a broken hook id/entry/regex is caught. Skips cleanly where
    # pre-commit is not installed (e.g. a minimal CI image), like verify_responsive does.
    precommit = ROOT / ".venv" / "bin" / "pre-commit"
    if not precommit.exists():
        pytest.skip("pre-commit not installed")
    result = subprocess.run(
        [str(precommit), "run", "check-analysis-json", "--all-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
