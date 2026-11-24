import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_harness.state import state_dir
from agent_harness.supervisor import (
    COMMAND_NOT_FOUND_EXIT_CODE,
    Supervisor,
    request_reload,
    serve_running,
    should_reload,
)

WAIT_SECONDS = 10.0
CHILD_SCRIPT = (
    "import os, sys, time\n"
    "with open(sys.argv[1], 'a') as f: f.write(f'{os.getpid()}\\n')\n"
    "time.sleep(60)\n"
)


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def started_pids(log: Path) -> list[int]:
    if not log.exists():
        return []
    return [int(line) for line in log.read_text().split()]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    log = tmp_path / "starts.log"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agent_harness",
            "serve",
            "--",
            sys.executable,
            "-c",
            CHILD_SCRIPT,
            str(log),
        ],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    wait_until(lambda: len(started_pids(log)) == 1)
    yield process, log
    if process.poll() is None:
        process.kill()
        process.wait()


def test_should_reload_matches_globs() -> None:
    globs = ("src/**/*.py",)

    assert should_reload(["src/app.py"], globs)
    assert should_reload(["src/pkg/deep/app.py"], globs)
    assert not should_reload(["tests/test_app.py", "README.md"], globs)


def test_reload_without_server_is_refused(tmp_path: Path) -> None:
    assert not serve_running(tmp_path)
    assert not request_reload(tmp_path)


def test_stale_pid_is_not_running(tmp_path: Path) -> None:
    (state_dir(tmp_path) / "serve.pid").write_text("999999")

    assert not serve_running(tmp_path)


def test_reload_restarts_child_once(
    served: tuple[subprocess.Popen[bytes], Path], tmp_path: Path
) -> None:
    _, log = served
    wait_until(lambda: serve_running(tmp_path))
    first = started_pids(log)[0]

    assert request_reload(tmp_path)

    wait_until(lambda: len(started_pids(log)) == 2)
    wait_until(lambda: not alive(first))
    time.sleep(0.3)
    assert len(started_pids(log)) == 2


def test_sigterm_stops_child_and_cleans_up(
    served: tuple[subprocess.Popen[bytes], Path], tmp_path: Path
) -> None:
    process, log = served
    child = started_pids(log)[0]

    process.send_signal(signal.SIGTERM)

    assert process.wait(timeout=WAIT_SECONDS) == 0
    wait_until(lambda: not alive(child))
    assert not (state_dir(tmp_path) / "serve.pid").exists()


def test_missing_command_exits_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = Supervisor(["no-such-server-xyz"], tmp_path).run()

    assert code == COMMAND_NOT_FOUND_EXIT_CODE
    assert "no-such-server-xyz not found" in capsys.readouterr().err
    assert not (state_dir(tmp_path) / "serve.pid").exists()


def test_command_resolves_from_project_venv(tmp_path: Path) -> None:
    log = tmp_path / "starts.log"
    script = tmp_path / ".venv" / "bin" / "fake-server"
    script.parent.mkdir(parents=True)
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, time\n"
        f"open({str(log)!r}, 'a').write(f'{{os.getpid()}}\\n')\n"
        "time.sleep(60)\n"
    )
    script.chmod(0o755)
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_harness", "serve", "--", "fake-server"],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    try:
        wait_until(lambda: len(started_pids(log)) == 1)
    finally:
        process.terminate()
        process.wait(timeout=WAIT_SECONDS)
