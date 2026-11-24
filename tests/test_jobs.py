import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tether.cli import on_edit, on_prompt, on_stop, status
from tether.config import Config, load_config
from tether.hooks import BLOCK_EXIT_CODE, HookInput
from tether.jobs import (
    job_running,
    latest_result,
    start_job,
    stop_job,
    take_result,
)
from tether.state import load_turn, record_edit
from tether.verify import TurnSnapshot

PASS = ("python", "-c", "import sys; sys.exit(0)")
FAIL = ("python", "-c", "import sys; print('boom'); sys.exit(1)")
SLOW = ("python", "-c", "import time; time.sleep(30)")
WAIT_SECONDS = 15.0


def write(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def make_config(root: Path, **overrides: Any) -> Config:
    values: dict[str, Any] = {
        "lint_command": PASS,
        "typecheck_command": PASS,
        "test_command": PASS,
        "summary_on_stop": False,
        **overrides,
    }
    lines = [f"{key} = {json.dumps(value)}" for key, value in values.items()]
    (root / "pyproject.toml").write_text("[tool.tether]\n" + "\n".join(lines))
    return load_config(root)


def stop_hook(root: Path) -> HookInput:
    return HookInput(event="Stop", cwd=root)


def edit_hook(root: Path, relative: str) -> HookInput:
    return HookInput(event="PostToolUse", cwd=root, file_path=root / relative)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path, "src/orders.py")
    write(tmp_path, "tests/test_orders.py")
    return tmp_path


def test_stop_returns_before_slow_checks_finish(project: Path) -> None:
    config = make_config(project, test_command=SLOW)
    record_edit(project, "src/orders.py")

    started = time.monotonic()
    outcome = on_stop(config, stop_hook(project), now=5.0)
    elapsed = time.monotonic() - started

    assert outcome.exit_code == 0
    assert elapsed < 2.0
    assert job_running(project)
    assert load_turn(project).edited == []
    stop_job(project)
    assert not job_running(project)


def test_failures_reach_agent_on_next_prompt_once(project: Path) -> None:
    config = make_config(project, test_command=FAIL)
    record_edit(project, "src/orders.py")

    on_stop(config, stop_hook(project), now=5.0)
    wait_until(lambda: latest_result(project) is not None)

    first = on_prompt(config, now=6.0)
    second = on_prompt(config, now=7.0)
    assert "background checks of your previous turn" in first.stdout
    assert "## tests failed" in first.stdout
    assert second.stdout == ""


def test_failures_reach_agent_on_next_edit(project: Path) -> None:
    config = make_config(project, test_command=FAIL)
    record_edit(project, "src/orders.py")
    on_stop(config, stop_hook(project), now=5.0)
    wait_until(lambda: latest_result(project) is not None)

    outcome = on_edit(config, edit_hook(project, "src/orders.py"))

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "boom" in outcome.stderr
    assert on_edit(config, edit_hook(project, "src/orders.py")).exit_code == 0


def test_passing_checks_stay_quiet(project: Path) -> None:
    config = make_config(project)
    record_edit(project, "src/orders.py")
    on_stop(config, stop_hook(project), now=5.0)
    wait_until(lambda: latest_result(project) is not None)

    assert on_prompt(config, now=6.0).stdout == ""
    assert "all clear" in status(config).stdout


def test_stop_without_changes_starts_nothing(project: Path) -> None:
    on_stop(make_config(project), stop_hook(project), now=5.0)

    assert not job_running(project)
    assert latest_result(project) is None


def test_new_job_replaces_running_one(project: Path) -> None:
    slow = make_config(project, test_command=SLOW)
    record_edit(project, "src/orders.py")
    snapshot = TurnSnapshot(0.0, ("src/orders.py",), "")
    start_job(slow, snapshot)
    assert job_running(project)

    newest = start_job(make_config(project, test_command=FAIL), snapshot)

    wait_until(lambda: latest_result(project) is not None)
    result = take_result(project)
    assert result is not None
    assert result.job_id == newest
    assert result.problems
    assert "tether: checks failed." in result.user_message
