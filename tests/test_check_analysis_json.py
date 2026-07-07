"""Tests for the pre-commit JSON validity hook (roadmap #5)."""

import json

from tools.check_analysis_json import find_invalid, main


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
