import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from types import FrameType

from agent_harness.state import state_dir

POLL_SECONDS = 0.1
STOP_GRACE_SECONDS = 5.0
SERVE_PID_FILE = "serve.pid"
RELOAD_REQUEST_FILE = "reload.request"


def should_reload(changed: Iterable[str], globs: Sequence[str]) -> bool:
    return any(
        PurePosixPath(path).full_match(pattern)
        for path in changed
        for pattern in globs
    )


def serve_running(root: Path) -> bool:
    try:
        pid = int((state_dir(root) / SERVE_PID_FILE).read_text())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def request_reload(root: Path) -> bool:
    if not serve_running(root):
        return False
    (state_dir(root) / RELOAD_REQUEST_FILE).touch()
    return True


class Supervisor:
    def __init__(self, command: Sequence[str], root: Path) -> None:
        self._command = list(command)
        self._root = root
        self._directory = state_dir(root)
        self._child: subprocess.Popen[bytes] | None = None
        self._stop_requested = False
        self._reported_exit = False

    def run(self) -> int:
        pid_path = self._directory / SERVE_PID_FILE
        pid_path.write_text(str(os.getpid()))
        self._consume_reload_request()
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        try:
            self._start()
            while not self._stop_requested:
                if self._consume_reload_request():
                    self._log("reloading")
                    self._terminate()
                    self._start()
                self._report_unexpected_exit()
                time.sleep(POLL_SECONDS)
        finally:
            self._terminate()
            if pid_path.read_text() == str(os.getpid()):
                pid_path.unlink()
        return 0

    def _start(self) -> None:
        self._child = subprocess.Popen(
            self._command, cwd=self._root, start_new_session=True
        )
        self._reported_exit = False

    def _terminate(self) -> None:
        child, self._child = self._child, None
        if child is None or child.poll() is not None:
            return
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()

    def _consume_reload_request(self) -> bool:
        request = self._directory / RELOAD_REQUEST_FILE
        try:
            request.unlink()
        except FileNotFoundError:
            return False
        return True

    def _report_unexpected_exit(self) -> None:
        if self._child is None or self._reported_exit:
            return
        code = self._child.poll()
        if code is not None:
            self._reported_exit = True
            self._log(f"server exited with code {code}; waiting for reload")

    def _request_stop(self, signum: int, frame: FrameType | None) -> None:
        self._stop_requested = True

    def _log(self, message: str) -> None:
        print(f"harness serve: {message}", file=sys.stderr, flush=True)
