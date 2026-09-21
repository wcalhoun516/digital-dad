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
import subprocess
import sys
import threading

import pytest

from console import jobs


class FakeProc:
    """A subprocess that never was: it holds until released, then reports an exit code."""

    def __init__(self, argv, *, cwd=None, stdout=None, stderr=None, stdin=None, exit_code=0):
        self.args = list(argv)
        self.cwd = cwd
        self.stdout_handle = stdout
        self.stderr = stderr
        self.stdin = stdin
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
    """A spawn hook that records every launch and hands back a FakeProc.

    Anything still held at teardown is released. A watcher thread left waiting on a job that
    never ends outlives its test and surfaces minutes later as an unexplained warning
    against whichever test happened to be running when it finally gave up.
    """
    procs = []

    def spawn(argv, **kwargs):
        proc = FakeProc(argv, **kwargs)
        procs.append(proc)
        return proc

    spawn.procs = procs
    spawn.watchers = []
    yield spawn
    for proc in procs:
        proc.release()
    for watcher in spawn.watchers:
        watcher.join(5)


@pytest.fixture
def state_path(tmp_path):
    """The one path the runner needs: logs live beside it, so nothing threads two paths."""
    return tmp_path / "console" / "job.json"


def _start(spawn, state_path, name="ingest", **kwargs):
    state, watcher = jobs.start_job(
        name, state_path=state_path, spawn=spawn, python="/fake/python", **kwargs
    )
    spawn.watchers.append(watcher)
    return state, watcher


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


def test_the_child_is_wired_so_nothing_it_says_is_lost_and_nothing_can_block_it(
    spawned, state_path
):
    """stderr into the log, stdin closed.

    A traceback on the *server's* stderr is invisible to an operator who only has a
    browser, and a child that stops on an input prompt would hold the single job slot
    until someone found it with a terminal — the exact situation the console removes.
    """
    _start(spawned, state_path)
    assert spawned.procs[0].stderr is subprocess.STDOUT
    assert spawned.procs[0].stdin is subprocess.DEVNULL


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


def test_a_poll_that_beats_the_watcher_does_not_call_a_finished_job_interrupted(
    spawned, state_path
):
    """The child exits; the watcher has not written the outcome yet; the page polls.

    `interrupted` has to mean "nobody is coming to write the real answer". While this
    process still holds a watcher for the run, someone is — and calling it interrupted
    would freeze that word on the page for a job that in fact succeeded, because the page
    stops polling the moment it sees a terminal state.
    """
    _, watcher = _start(spawned, state_path)
    assert jobs.job_state(state_path, alive=lambda pid: False)["state"] == "running"
    _finish(spawned.procs[0], watcher)
    assert jobs.job_state(state_path, alive=lambda pid: False)["state"] == "succeeded"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_watcher_that_cannot_write_still_lets_the_run_be_reconciled(
    spawned, state_path, monkeypatch
):
    """The watcher's own write can fail — a full disk, a removed directory.

    Its failure must not also cost the fallback. If the run stayed claimed by a watcher
    that is gone, nothing would ever reconcile the `running` record it left behind, and
    the console would refuse every future job until someone restarted the server: the
    exact stale lock this module exists to prevent.
    """
    _, watcher = _start(spawned, state_path)

    def full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(jobs, "_write", full_disk)
    spawned.procs[0].release()
    watcher.join(5)
    monkeypatch.undo()
    assert jobs.job_state(state_path, alive=lambda pid: False)["state"] == "interrupted"


def test_concurrent_writers_do_not_collide_on_one_temp_file(state_path):
    """Handler threads poll while the watcher finishes: several writers, one state file.

    A temp name shared by every writer means the first `replace` moves the file out from
    under the second, which loses that write entirely — and the write being lost is the
    job's final outcome.
    """
    errors = []

    def hammer(n):
        try:
            for i in range(50):
                jobs._write(state_path, {"job": "x", "state": "running", "n": [n, i]})
        except Exception as exc:  # noqa: BLE001 - the failure itself is the result
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert errors == []
    assert json.loads(state_path.read_text())["job"] == "x"


def test_a_live_process_is_still_running(spawned, state_path):
    _start(spawned, state_path)
    assert jobs.job_state(state_path, alive=lambda pid: True)["state"] == "running"


def test_a_process_that_has_exited_is_not_alive():
    """The one test that exercises the real liveness check rather than an injected one.

    Everything above passes `alive=`, so a `_pid_alive` that always answered True would
    go unnoticed here and wedge the runner on the first crashed server.
    """
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    assert jobs._pid_alive(proc.pid) is False


def test_a_process_we_are_not_allowed_to_signal_is_still_alive():
    """pid 1 is not ours. `os.kill` says EPERM, which means "there, but not yours".

    Reading that as dead would let the console start a second job on top of a live one
    whenever the runner and the child belong to different users.
    """
    assert jobs._pid_alive(1) is True


def test_an_unreadable_state_file_reads_as_idle_rather_than_raising(state_path):
    """A truncated write must not take the whole console down with it."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not json", encoding="utf-8")
    assert jobs.job_state(state_path)["state"] == "idle"


# --- the log ---------------------------------------------------------------------------


def test_two_runs_in_the_same_second_do_not_share_a_log(state_path):
    """The stamp has one-second resolution and a finished job can be restarted at once.

    Appending onto the previous run's file would hand the operator a single log claiming
    to be two runs, with no boundary between them and the earlier run's failure buried in
    the middle of the later one.
    """
    first, first_name = jobs._open_log(state_path, "ingest", "20260921T000000")
    first.write("run one\n")
    first.close()
    second, second_name = jobs._open_log(state_path, "ingest", "20260921T000000")
    second.close()
    assert second_name != first_name
    assert (state_path.parent / "logs" / second_name).read_text() == ""


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


# --- a start that cannot happen --------------------------------------------------------


def test_a_spawn_that_fails_is_a_job_error_not_an_oserror(state_path):
    """A missing interpreter or an exhausted process table must arrive as a refusal.

    The route turns `JobError` into a message the operator can read. An `OSError` escaping
    this far reaches them as a 500 and a traceback instead.
    """
    def boom(*_args, **_kwargs):
        raise OSError(8, "Exec format error")

    with pytest.raises(jobs.JobError) as caught:
        jobs.start_job("ingest", state_path=state_path, spawn=boom)
    assert "Exec format error" in str(caught.value)


def test_a_failed_start_leaves_no_running_record_behind(state_path):
    """Otherwise the runner would be wedged by a job that never existed."""
    def boom(*_args, **_kwargs):
        raise OSError("no")

    with pytest.raises(jobs.JobError):
        jobs.start_job("ingest", state_path=state_path, spawn=boom)
    assert jobs.job_state(state_path)["state"] == "idle"


def test_a_failed_start_does_not_litter_an_empty_log(state_path):
    """The log is opened before the spawn, so a refused start has to clean it up."""
    def boom(*_args, **_kwargs):
        raise OSError("no")

    with pytest.raises(jobs.JobError):
        jobs.start_job("ingest", state_path=state_path, spawn=boom)
    assert list((state_path.parent / "logs").glob("*.log")) == []
