"""Tests for training/retrain_watch.py — retrain LoRA when the corpus actually grows.

D15/D19/D20 all measured LoRA at ~453k tokens and it never helped, but every run was
token-starved (val loss bottoms at 0.74 epochs). The hypothesis under test is now corpus
*size*, so the job of this module is to notice when there is meaningfully more text and
trigger a fresh run — and, just as importantly, to NOT burn hours of GPU when someone
scraped three more articles.
"""

import json

import pytest

from training import retrain_watch as rw


def state(fp="abc", articles=181, tokens=453_000):
    return {"fingerprint": fp, "articles": articles, "approx_tokens": tokens}


# --- the decision ----------------------------------------------------------------

def test_due_when_there_is_no_prior_run():
    d = rw.retrain_decision(state(), None, min_new_tokens=25_000)
    assert d.due and "no prior" in d.reason.lower()


def test_not_due_when_the_fingerprint_is_unchanged():
    cur = state()
    d = rw.retrain_decision(cur, dict(cur), min_new_tokens=25_000)
    assert not d.due and "unchanged" in d.reason.lower()


def test_not_due_when_growth_is_below_the_threshold():
    """Three new articles must not cost hours of GPU."""
    last = state(fp="old", tokens=453_000)
    cur = state(fp="new", tokens=458_000)          # +5k
    d = rw.retrain_decision(cur, last, min_new_tokens=25_000)
    assert not d.due
    assert "5,000" in d.reason or "5000" in d.reason


def test_due_when_growth_clears_the_threshold():
    last = state(fp="old", tokens=453_000)
    cur = state(fp="new", tokens=560_000)          # +107k, about one book
    d = rw.retrain_decision(cur, last, min_new_tokens=25_000)
    assert d.due
    assert d.new_tokens == 107_000


def test_due_exactly_at_the_threshold():
    d = rw.retrain_decision(state(fp="new", tokens=478_000),
                            state(fp="old", tokens=453_000), min_new_tokens=25_000)
    assert d.due


def test_a_large_shrink_also_triggers():
    """A corpus that lost 100k tokens changed materially — a stale adapter is wrong
    in that direction too."""
    d = rw.retrain_decision(state(fp="new", tokens=350_000),
                            state(fp="old", tokens=453_000), min_new_tokens=25_000)
    assert d.due and d.new_tokens < 0


def test_fingerprint_change_is_required_not_just_token_count():
    """Token estimates wobble; the fingerprint is the authority on 'did the corpus change'."""
    d = rw.retrain_decision(state(fp="same", tokens=600_000),
                            state(fp="same", tokens=453_000), min_new_tokens=25_000)
    assert not d.due


def test_decision_reports_the_numbers_for_the_log():
    d = rw.retrain_decision(state(fp="new", tokens=560_000),
                            state(fp="old", tokens=453_000), min_new_tokens=25_000)
    assert "560" in d.reason.replace(",", "") or "107" in d.reason.replace(",", "")


# --- state persistence -----------------------------------------------------------

def test_record_and_load_round_trip(tmp_path):
    p = tmp_path / "s.json"
    rw.record_state(state(fp="xyz"), p)
    assert rw.load_last_state(p)["fingerprint"] == "xyz"


def test_load_last_state_absent_is_none(tmp_path):
    assert rw.load_last_state(tmp_path / "nope.json") is None


def test_load_last_state_corrupt_is_none_not_a_crash(tmp_path):
    """A half-written state file must not wedge every future run."""
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert rw.load_last_state(p) is None


def test_record_state_stamps_a_date(tmp_path):
    p = tmp_path / "s.json"
    rw.record_state(state(), p)
    assert "recorded_at" in json.loads(p.read_text())


# --- corpus measurement ----------------------------------------------------------

def test_corpus_state_counts_articles_and_tokens():
    arts = [{"slug": "a", "content_hash": "1", "body": "one two three four"},
            {"slug": "b", "content_hash": "2", "body": "five six"}]
    s = rw.corpus_state(arts)
    assert s["articles"] == 2
    assert s["words"] == 6
    assert s["approx_tokens"] > 0


def test_corpus_state_fingerprint_is_order_independent():
    a = [{"slug": "a", "content_hash": "1", "body": "x"},
         {"slug": "b", "content_hash": "2", "body": "y"}]
    assert rw.corpus_state(a)["fingerprint"] == rw.corpus_state(list(reversed(a)))["fingerprint"]


def test_corpus_state_fingerprint_moves_when_content_changes():
    a = [{"slug": "a", "content_hash": "1", "body": "x"}]
    b = [{"slug": "a", "content_hash": "2", "body": "x"}]
    assert rw.corpus_state(a)["fingerprint"] != rw.corpus_state(b)["fingerprint"]


# --- the pipeline (injected seam) ------------------------------------------------

def test_run_pipeline_executes_steps_in_order():
    calls = []
    rw.run_pipeline(step=lambda name, cmd: calls.append(name) or 0, train=True, evaluate=False)
    assert calls[:3] == ["prepare", "preflight", "train"]


def test_run_pipeline_aborts_when_the_preflight_fails():
    """The preflight is the gate that caught a real split leak. A failure must stop
    the run, not get forced past."""
    def step(name, cmd):
        return 1 if name == "preflight" else 0

    result = rw.run_pipeline(step=step, train=True, evaluate=False)
    assert not result.ok and result.failed_at == "preflight"


def test_run_pipeline_skips_training_when_not_requested():
    calls = []
    rw.run_pipeline(step=lambda n, c: calls.append(n) or 0, train=False, evaluate=False)
    assert "train" not in calls


def test_run_pipeline_only_evaluates_when_asked():
    """Evaluation spends real money on the T3 judge, so it is opt-in."""
    calls = []
    rw.run_pipeline(step=lambda n, c: calls.append(n) or 0, train=True, evaluate=True)
    assert "evaluate" in calls
    calls.clear()
    rw.run_pipeline(step=lambda n, c: calls.append(n) or 0, train=True, evaluate=False)
    assert "evaluate" not in calls


def test_run_pipeline_reports_ok_on_a_clean_pass():
    r = rw.run_pipeline(step=lambda n, c: 0, train=True, evaluate=True)
    assert r.ok and r.failed_at is None


@pytest.mark.parametrize("failing", ["prepare", "train", "evaluate"])
def test_run_pipeline_stops_at_the_first_failure(failing):
    seen = []

    def step(name, cmd):
        seen.append(name)
        return 1 if name == failing else 0

    r = rw.run_pipeline(step=step, train=True, evaluate=True)
    assert not r.ok and r.failed_at == failing
    assert seen[-1] == failing, "must not keep going after a failure"


def test_load_last_state_survives_an_unreadable_path(tmp_path):
    """JSONDecodeError subclasses ValueError, so the JSON test alone does not prove the
    OSError branch is caught — a directory where a file belongs does."""
    d = tmp_path / "state_is_a_dir"
    d.mkdir()
    assert rw.load_last_state(d) is None
