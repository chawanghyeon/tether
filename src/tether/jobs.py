import dataclasses
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from tether.checks import Deadline
from tether.config import Config
from tether.state import state_dir
from tether.verify import TurnSnapshot, verify_turn

JOB_FILE = "job.json"
JOB_PID_FILE = "job.pid"
JOB_LOG_FILE = "job.log"
RESULT_FILE = "result.json"
RESULT_LOCK = "result.lock"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"
JOB_COMMAND_MARKER = "run-job"
DELIVERY_HEADING = "tether: background checks of your previous turn found:"


@dataclasses.dataclass(frozen=True)
class StoredResult:
    job_id: int
    finished_at: float
    problems: bool
    agent_message: str
    user_message: str
    delivered: bool = False

    def delivery(self) -> str:
        return f"{DELIVERY_HEADING}\n\n{self.agent_message}"


def start_job(config: Config, snapshot: TurnSnapshot) -> int:
    stop_job(config.root)
    directory = state_dir(config.root)
    job_id = time.time_ns()
    job = {"job_id": job_id, "snapshot": dataclasses.asdict(snapshot)}
    _write_json(directory / JOB_FILE, job)
    with open(directory / JOB_LOG_FILE, "w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tether", JOB_COMMAND_MARKER],
            cwd=config.root,
            env={**os.environ, PROJECT_DIR_ENV: str(config.root)},
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    (directory / JOB_PID_FILE).write_text(str(process.pid))
    return job_id


def run_job(config: Config) -> int:
    directory = state_dir(config.root)
    job = json.loads((directory / JOB_FILE).read_text())
    raw = job["snapshot"]
    snapshot = TurnSnapshot(
        started_at=float(raw["started_at"]),
        edited=tuple(raw["edited"]),
        baseline=str(raw["baseline"]),
        transcript_path=raw.get("transcript_path"),
    )
    report = verify_turn(
        config, snapshot, Deadline.after(config.background_timeout_seconds)
    )
    result = StoredResult(
        job_id=int(job["job_id"]),
        finished_at=time.time(),
        problems=report.problems(config),
        agent_message=report.agent_message(config),
        user_message="\n".join(report.user_messages(attempts=None)),
    )
    with _locked(directory):
        current = json.loads((directory / JOB_FILE).read_text())
        if current["job_id"] == result.job_id:
            _write_json(directory / RESULT_FILE, dataclasses.asdict(result))
    _clear_pid(directory, os.getpid())
    return 0


def job_running(root: Path) -> bool:
    return _job_pid(root) is not None


def stop_job(root: Path) -> None:
    pid = _job_pid(root)
    if pid is not None:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGTERM)
    (state_dir(root) / JOB_PID_FILE).unlink(missing_ok=True)


def take_result(root: Path) -> StoredResult | None:
    directory = state_dir(root)
    with _locked(directory):
        result = _read_result(directory)
        if result is None or result.delivered:
            return None
        delivered = dataclasses.replace(result, delivered=True)
        _write_json(directory / RESULT_FILE, dataclasses.asdict(delivered))
    return result


def latest_result(root: Path) -> StoredResult | None:
    directory = state_dir(root)
    with _locked(directory):
        return _read_result(directory)


def _job_pid(root: Path) -> int | None:
    try:
        pid = int((state_dir(root) / JOB_PID_FILE).read_text())
    except (FileNotFoundError, ValueError):
        return None
    completed = subprocess.run(
        ("ps", "-o", "command=", "-p", str(pid)),
        capture_output=True,
        text=True,
    )
    is_ours = "tether" in completed.stdout and JOB_COMMAND_MARKER in (
        completed.stdout
    )
    return pid if is_ours else None


def _clear_pid(directory: Path, pid: int) -> None:
    path = directory / JOB_PID_FILE
    try:
        if int(path.read_text()) == pid:
            path.unlink()
    except (FileNotFoundError, ValueError):
        pass


def _read_result(directory: Path) -> StoredResult | None:
    try:
        raw = json.loads((directory / RESULT_FILE).read_text())
        return StoredResult(**raw)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return None


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    with open(directory / RESULT_LOCK, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _write_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data))
    os.replace(temporary, path)
