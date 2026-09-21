"""The console's job runner (plan 0011 step 4).

**No test here starts a real job.** Every one drives `console/jobs.py` with a fake spawn, so
the state machine — one job at a time, a 409 rather than a silent queue, a finished job that
stops blocking the next one — is proved without an hour of local GPU or a single paid call.

The one thing worth saying up front about the design: a job survives in a JSON file, but the
*process* does not survive the server. Kill the server mid-run and the record still says
`running` forever, which is the classic stale-lock bug — the console would refuse every
subsequent job until someone deleted a file by hand. So liveness is re-derived from the pid on
every read, and that is what most of these tests are about.
"""

import json
import os
import threading

import pytest

from console import jobs


class FakeProc:
    """A subprocess that never was: it holds until released, then reports an exit code."""

    def __init__(self, argv, *, cwd=None, stdout=None, stderr=None, stdin=None, exit_code=0):
        self.args = list(argv)
        self.cwd = cwd
        self.stdout_handle = stdout
        # A real child is alive between spawn and exit, and the runner re-derives that from
        # the pid. Borrowing the test process's own pid makes the fake honest about it
        # without inventing a number the OS would report as dead.
        self.pid = os.getpid()
        self._exit_code = exit_code
        self._released = threading.Event()

    def wait(self):
        assert self._released.wait(5), "the fake job was never released"
        return self._exit_code

    def release(self):
        self._released.set()

    def write(self, text):
        """Write to the job's log the way a real child's stdout would."""
        self.stdout_handle.write(text)
        self.stdout_handle.flush()


@pytest.fixture
def spawned():
    """A spawn hook that records every launch and hands back a FakeProc."""
    procs = []

    def spawn(argv, **kwargs):
        proc = FakeProc(argv, **kwargs)
        procs.append(proc)
        return proc

    spawn.procs = procs
    return spawn


@pytest.fixture
def state_path(tmp_path):
    """The one path the runner needs: logs live beside it, so nothing threads two paths."""
    return tmp_path / "console" / "job.json"


def _start(spawn, state_path, name="ingest", **kwargs):
    return jobs.start_job(
        name, state_path=state_path, spawn=spawn, python="/fake/python", **kwargs
    )


# --- the registry ---------------------------------------------------------------------


def test_the_ingest_job_is_registered():
    """Step 4's headline: the console can finally stage the inbox without a terminal."""
    assert "ingest" in jobs.JOBS
    assert jobs.JOBS["ingest"].argv == ("-m", "ingest")


def test_every_job_runs_a_python_module():
    """No shell strings. An argv list with -m cannot be a command-injection surface."""
    for spec in jobs.JOBS.values():
        assert spec.argv[0] == "-m", spec


def test_the_expensive_jobs_are_flagged_as_such():
    """`train` is hours of GPU and `voice-eval` spends real money on T3 judge calls.

    The page turns this flag into a confirmation prompt; without it a misplaced click costs
    either an afternoon or actual dollars.
    """
    assert jobs.JOBS["train"].costly is True
    assert jobs.JOBS["voice-eval"].costly is True
    assert jobs.JOBS["ingest"].costly is False


# --- starting ------------------------------------------------------------------------


def test_nothing_has_run_yet_reads_as_idle(state_path):
    assert jobs.job_state(state_path)["state"] == "idle"


def test_start_spawns_the_registered_command(spawned, state_path):
    _start(spawned, state_path, "finetune-preflight")
    assert spawned.procs[0].args == ["/fake/python", "-m", "training.finetune_preflight"]


def test_start_records_a_running_job(spawned, state_path):
    state, _ = _start(spawned, state_path)
    assert state["job"] == "ingest"
    assert state["state"] == "running"
    assert state["pid"] == os.getpid()
    assert state["exit_code"] is None
    assert jobs.job_state(state_path)["state"] == "running"


def test_the_state_file_names_the_log_but_never_its_path(spawned, state_path):
    """Same rule as the upload route: the operator gets a filename, not a server path."""
    state, _ = _start(spawned, state_path)
    assert state["log"] == (state_path.parent / "logs" / state["log"]).name
    assert "/" not in state["log"]


def test_an_unknown_job_name_is_refused(spawned, state_path):
    with pytest.raises(jobs.UnknownJob):
        _start(spawned, state_path, "rm-rf")
    assert not spawned.procs


def test_a_second_job_is_refused_while_one_runs(spawned, state_path):
    """Refused, not queued. A silent queue is how you end up with two trainers on one GPU."""
    _start(spawned, state_path)
    with pytest.raises(jobs.JobBusy):
        _start(spawned, state_path, "finetune-prep")
    assert len(spawned.procs) == 1


# --- finishing -----------------------------------------------------------------------


def _finish(proc, watcher, exit_code=0):
    proc._exit_code = exit_code
    proc.release()
    watcher.join(5)
    assert not watcher.is_alive()


def test_a_finished_job_records_its_exit_code(spawned, state_path):
    _, watcher = _start(spawned, state_path)
    _finish(spawned.procs[0], watcher)
    state = jobs.job_state(state_path)
    assert state["state"] == "succeeded"
    assert state["exit_code"] == 0
    assert state["finished_at"]


def test_a_nonzero_exit_is_a_failure_not_a_success(spawned, state_path):
    _, watcher = _start(spawned, state_path)
    _finish(spawned.procs[0], watcher, exit_code=2)
    state = jobs.job_state(state_path)
    assert state["state"] == "failed"
    assert state["exit_code"] == 2


def test_a_finished_job_stops_blocking_the_next_one(spawned, state_path):
    _, watcher = _start(spawned, state_path)
    _finish(spawned.procs[0], watcher)
    state, _ = _start(spawned, state_path, "finetune-prep")
    assert state["job"] == "finetune-prep"


# --- the stale-lock bug ---------------------------------------------------------------


def _leave_a_running_record(state_path):
    """What the state file looks like after the server was killed mid-job."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "job": "train", "state": "running", "pid": 999999, "exit_code": None,
        "started_at": "2026-09-21T00:00:00+00:00", "finished_at": None, "log": "x.log",
    }), encoding="utf-8")


def test_a_running_record_whose_process_is_gone_reads_as_interrupted(state_path):
    """The server was killed mid-job. The child died with it; the file still says running."""
    _leave_a_running_record(state_path)
    state = jobs.job_state(state_path, alive=lambda pid: False)
    assert state["state"] == "interrupted"


def test_an_interrupted_job_does_not_block_the_next_one_forever(spawned, state_path):
    """The reconciliation is written back, so recovery does not need a human deleting a file."""
    _leave_a_running_record(state_path)
    jobs.job_state(state_path, alive=lambda pid: False)
    assert json.loads(state_path.read_text())["state"] == "interrupted"
    state, _ = _start(spawned, state_path)
    assert state["state"] == "running"


def test_a_live_process_is_still_running(spawned, state_path):
    _start(spawned, state_path)
    assert jobs.job_state(state_path, alive=lambda pid: True)["state"] == "running"


def test_an_unreadable_state_file_reads_as_idle_rather_than_raising(state_path):
    """A truncated write must not take the whole console down with it."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not json", encoding="utf-8")
    assert jobs.job_state(state_path)["state"] == "idle"


# --- the log ---------------------------------------------------------------------------


def test_the_tail_carries_what_the_job_wrote(spawned, state_path):
    _start(spawned, state_path)
    spawned.procs[0].write("staged 3 documents\n")
    assert jobs.tail_log(state_path)["text"] == "staged 3 documents\n"


def test_the_tail_resumes_from_an_offset_so_no_line_arrives_twice(spawned, state_path):
    """The page polls. Without an offset every poll would re-deliver the whole log."""
    _start(spawned, state_path)
    spawned.procs[0].write("first\n")
    first = jobs.tail_log(state_path)
    spawned.procs[0].write("second\n")
    second = jobs.tail_log(state_path, offset=first["offset"])
    assert second["text"] == "second\n"


def test_a_flooding_job_cannot_hand_the_browser_more_than_the_cap(spawned, state_path):
    """An analysis run can print for hours; the tail is the last N bytes, not all of them."""
    _start(spawned, state_path)
    spawned.procs[0].write("x" * 5000)
    tail = jobs.tail_log(state_path, max_bytes=100)
    assert len(tail["text"]) == 100
    assert tail["size"] == 5000
    assert tail["offset"] == 5000


def test_an_offset_past_the_end_restarts_rather_than_returning_nothing(spawned, state_path):
    """The next run's log is a new, shorter file — a stale offset must not blank the view."""
    _start(spawned, state_path)
    spawned.procs[0].write("short\n")
    assert jobs.tail_log(state_path, offset=99999)["text"] == "short\n"


def test_there_is_no_tail_before_anything_has_run(state_path):
    assert jobs.tail_log(state_path) == {"text": "", "offset": 0, "size": 0}


def test_a_missing_log_file_is_empty_rather_than_an_error(spawned, state_path):
    """The record can outlive its log — a cleaned logs/ dir is not a 500."""
    _start(spawned, state_path)
    (state_path.parent / "logs" / jobs.job_state(state_path)["log"]).unlink()
    assert jobs.tail_log(state_path)["text"] == ""
