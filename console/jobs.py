"""Run one named pipeline step at a time, as a subprocess, and remember how it went.

Plan 0011 step 4. The console's crank: the operator clicks `ingest` and the inbox becomes a
review queue, without a terminal. Three rules shape everything here.

**Never in the request handler.** A `make ingest` takes minutes and a training run takes
hours; a handler thread that waits for either is a hung browser tab and, on this stdlib
server, a leaked thread. The child is spawned, the handler returns immediately, and a watcher
thread records the outcome.

**One job at a time, refused rather than queued.** Two `finetune-prep` runs writing the same
staged data, or two trainers on one GPU, is a corrupt result rather than a slow one. A second
start raises `JobBusy`, which the route turns into a 409.

**Liveness is re-derived, never trusted.** The state file survives a crash but the process
does not. A record still saying `running` with nothing behind it would refuse every future
job forever, so every read checks the pid and rewrites a dead `running` as `interrupted`.

The commands are argv lists of `python -m module`, never shell strings, and the set of them
is a closed registry — an operator picks a name, never a command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "console" / "job.json"

# The tail the page asks for on each poll. A job that floods stdout must not be able to hand
# the browser megabytes; past this the reader skips forward and says so.
MAX_TAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class JobSpec:
    argv: tuple[str, ...]
    summary: str
    costly: bool = False


# The flywheel, in the order the operator turns it. `costly` marks the two that cost something
# irreversible — hours of local GPU, or paid T3 judge calls — so the page can ask twice.
JOBS: dict[str, JobSpec] = {
    "ingest": JobSpec(
        ("-m", "ingest"),
        "Extract everything in data/inbox/ into the review queue above.",
    ),
    "finetune-prep": JobSpec(
        ("-m", "training.finetune_config"),
        "Stage the trainer's data from the leakage-free split (refuses if preflight fails).",
    ),
    "finetune-preflight": JobSpec(
        ("-m", "training.finetune_preflight"),
        "Check the split against the QLoRA config: chat shape, disjointness, length budget.",
    ),
    "voice-style": JobSpec(
        ("-m", "analysis.voice_eval", "--style-only"),
        "The free, offline half of the voice eval: style metrics, no judge.",
    ),
    "train": JobSpec(
        ("-m", "training.retrain_watch", "--run"),
        "Prepare → preflight → train. Hours of local GPU.",
        costly=True,
    ),
    "voice-eval": JobSpec(
        ("-m", "analysis.voice_eval"),
        "The full blind-A/B voice eval. Makes paid T3 judge calls.",
        costly=True,
    ),
}

# start_job is called from handler threads, so the "is one already running?" check and the
# claim that follows it have to be one step. Single server process, so a lock is enough.
_START_LOCK = threading.Lock()

# Runs this process still has a watcher for, by log name. `interrupted` means "nobody is
# coming to write the real outcome", and between the child's exit and the watcher's write
# that is false — so a poll in that window must not claim it.
_WATCHED: set[str] = set()
_WATCH_LOCK = threading.Lock()


class JobError(Exception):
    """Anything the operator asked for that cannot be done."""


class UnknownJob(JobError):
    pass


class JobBusy(JobError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log_dir(state_path: Path) -> Path:
    return Path(state_path).parent / "logs"


def _pid_alive(pid: int) -> bool:
    """Signal 0 checks for the process without touching it.

    A recycled pid would read as alive and hold the lock until that unrelated process exits.
    Accepted: the alternative is a pid-plus-start-time check that is platform-specific, and
    the cost of the rare false positive is one refused click, not a corrupt run.
    """
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # alive, just not ours to signal
    return True


def _read(state_path: Path) -> dict | None:
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A half-written or absent file is "nothing is running", not a 500. The console has to
        # stay usable in exactly the situation that produced a truncated write.
        return None
    return state if isinstance(state, dict) else None


def _write(state_path: Path, state: dict) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temp name is per-thread: a watcher writing the final outcome while two handler
    # threads poll is three writers on one path, and a shared temp name means the first
    # `replace` moves the file out from under the second, losing that write.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic: a poll never sees half a record


def _open_log(state_path: Path, name: str, stamp: str):
    """A fresh log file per run, never an append onto someone else's."""
    directory = _log_dir(state_path)
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{stamp}-{name}"
    for suffix in ("", *(f"-{n}" for n in range(2, 100))):
        try:
            handle = open(directory / f"{base}{suffix}.log", "x", encoding="utf-8")
        except FileExistsError:
            continue
        return handle, f"{base}{suffix}.log"
    raise JobError("could not open a log file for this run")


def _watched(log_name) -> bool:
    with _WATCH_LOCK:
        return log_name in _WATCHED


def job_state(state_path: Path | None = None, *, alive=_pid_alive) -> dict:
    """The current job, reconciled against reality.

    Writes when it reconciles: a `running` record with no process behind it becomes
    `interrupted` on disk, so recovery from a crashed server needs no human with a terminal.
    """
    state_path = Path(state_path or STATE_PATH)
    state = _read(state_path)
    if state is None:
        return {"state": "idle"}
    if state.get("state") == "running" and not _watched(state.get("log")) and not alive(
        state.get("pid") or -1
    ):
        state["state"] = "interrupted"
        state["finished_at"] = state.get("finished_at") or _now()
        _write(state_path, state)
    return state


def start_job(
    name: str,
    *,
    state_path: Path | None = None,
    python: str | None = None,
    cwd: Path | None = None,
    spawn=None,
    alive=_pid_alive,
) -> tuple[dict, threading.Thread]:
    """Launch `name` and return (its state, the thread watching it).

    The thread is returned so a test can join it; the route ignores it.
    """
    spec = JOBS.get(name)
    if spec is None:
        raise UnknownJob(f"unknown job: {name!r} (known: {', '.join(JOBS)})")

    state_path = Path(state_path or STATE_PATH)
    with _START_LOCK:
        current = job_state(state_path, alive=alive)
        if current.get("state") == "running":
            raise JobBusy(f"{current.get('job')} is already running")

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        handle, log_name = _open_log(state_path, name, stamp)
        argv = [python or sys.executable, *spec.argv]
        try:
            proc = (spawn or subprocess.Popen)(
                argv,
                cwd=str(cwd or ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            # No process, so no state is written: a start that never happened must not wedge
            # the runner, and its empty log is noise in a directory the operator reads.
            handle.close()
            Path(handle.name).unlink(missing_ok=True)
            raise JobError(f"could not start {name}: {exc}") from exc

        state = {
            "job": name,
            "state": "running",
            "pid": proc.pid,
            "argv": argv,
            "log": log_name,
            "started_at": _now(),
            "finished_at": None,
            "exit_code": None,
        }
        with _WATCH_LOCK:
            _WATCHED.add(log_name)
        _write(state_path, state)

    watcher = threading.Thread(
        target=_watch, args=(proc, handle, state_path, dict(state)), daemon=True
    )
    watcher.start()
    return state, watcher


def tail_log(
    state_path: Path | None = None, *, offset: int = 0, max_bytes: int = MAX_TAIL_BYTES
) -> dict:
    """The current job's log from `offset` on, plus the offset to ask from next time.

    Byte offsets rather than a stream. An SSE tail would hold one handler thread per viewer
    for the length of a training run and still need tearing down when the job ends; a poll
    that says "I have the first N bytes" delivers each line exactly once, costs a stat and a
    seek, and survives a closed laptop.
    """
    state_path = Path(state_path or STATE_PATH)
    name = (_read(state_path) or {}).get("log")
    empty = {"text": "", "offset": 0, "size": 0}
    if not name:
        return empty
    path = _log_dir(state_path) / name
    try:
        size = path.stat().st_size
    except OSError:
        return empty

    start = max(0, int(offset))
    if start > size:
        start = 0  # a newer, shorter log: the offset belongs to a run that is over
    start = max(start, size - max_bytes)
    with open(path, "rb") as handle:
        handle.seek(start)
        chunk = handle.read(max_bytes)
    # Decoding a window of bytes can split a multi-byte character at either edge; "replace"
    # costs one U+FFFD in a log line rather than an exception in the poll loop.
    return {"text": chunk.decode("utf-8", "replace"), "offset": start + len(chunk), "size": size}


def _watch(proc, handle, state_path: Path, state: dict) -> None:
    try:
        try:
            code = proc.wait()
        finally:
            handle.close()
        state["exit_code"] = code
        state["state"] = "succeeded" if code == 0 else "failed"
        state["finished_at"] = _now()
        _write(state_path, state)
    finally:
        # Released last, and even if the write above failed: a run left in the watched set
        # would never be reconciled, which is the stale lock this module exists to avoid.
        with _WATCH_LOCK:
            _WATCHED.discard(state["log"])


