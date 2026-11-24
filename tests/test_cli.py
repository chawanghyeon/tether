import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from tether.cli import (
    check,
    hooks_settings,
    on_edit,
    on_prompt,
    on_stop,
)
from tether.config import Config, ForbiddenPattern, ImportRule
from tether.hooks import BLOCK_EXIT_CODE, HookInput
from tether.state import load_turn, record_edit
from tether.supervisor import RELOAD_REQUEST_FILE

PASS = ("python", "-c", "import sys; sys.exit(0)")
FAIL = ("python", "-c", "import sys; print('broken'); sys.exit(1)")
SERVE_RUNNING = "tether.supervisor.serve_running"


def write(root: Path, relative: str, text: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def edit_hook(root: Path, relative: str) -> HookInput:
    return HookInput(
        event="PostToolUse",
        cwd=root,
        tool_name="Edit",
        file_path=root / relative,
    )


def stop_hook(root: Path, transcript: Path | None = None) -> HookInput:
    return HookInput(event="Stop", cwd=root, transcript_path=transcript)


def write_transcript(path: Path, final_text: str) -> Path:
    entries = [
        {"type": "user", "message": {"role": "user", "content": "go"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": final_text}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries))
    return path


def make_config(root: Path, **overrides: Any) -> Config:
    base = Config(
        root=root,
        lint_command=PASS,
        typecheck_command=PASS,
        test_command=PASS,
    )
    return dataclasses.replace(base, **overrides)


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    write(tmp_path, "src/orders.py")
    write(tmp_path, "tests/test_orders.py", "def test_x():\n    assert 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path, "src/orders.py")
    write(tmp_path, "tests/test_orders.py")
    return tmp_path


def test_on_prompt_starts_a_turn(project: Path) -> None:
    record_edit(project, "src/orders.py")

    on_prompt(make_config(project), now=50.0)

    turn = load_turn(project)
    assert turn.started_at == 50.0
    assert turn.edited == []


def test_on_edit_records_and_passes(project: Path) -> None:
    outcome = on_edit(make_config(project), edit_hook(project, "src/orders.py"))

    assert outcome.exit_code == 0
    assert load_turn(project).edited == ["src/orders.py"]


def test_on_edit_reports_lint_failure_to_agent(project: Path) -> None:
    config = make_config(project, lint_command=FAIL)

    outcome = on_edit(config, edit_hook(project, "src/orders.py"))

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "broken" in outcome.stderr


def test_on_edit_skips_lint_for_non_python(project: Path) -> None:
    write(project, "README.md")
    config = make_config(project, lint_command=FAIL)

    outcome = on_edit(config, edit_hook(project, "README.md"))

    assert outcome.exit_code == 0
    assert load_turn(project).edited == ["README.md"]


def test_on_edit_ignores_files_outside_project(project: Path) -> None:
    hook = HookInput(event="PostToolUse", cwd=project, file_path=Path("/x.py"))

    assert on_edit(make_config(project), hook).exit_code == 0
    assert load_turn(project).edited == []


def test_on_stop_passes_and_resets_turn(project: Path) -> None:
    record_edit(project, "src/orders.py")

    outcome = on_stop(make_config(project), stop_hook(project), now=99.0)

    assert outcome.exit_code == 0
    assert outcome.stdout == ""
    assert load_turn(project).edited == []
    assert load_turn(project).started_at == 99.0


def test_on_stop_blocks_until_attempts_run_out(project: Path) -> None:
    config = make_config(project, test_command=FAIL, max_stop_attempts=2)
    record_edit(project, "src/orders.py")

    first = on_stop(config, stop_hook(project), now=1.0)
    second = on_stop(config, stop_hook(project), now=2.0)
    third = on_stop(config, stop_hook(project), now=3.0)

    assert first.exit_code == BLOCK_EXIT_CODE
    assert "## tests failed" in first.stderr
    assert second.exit_code == BLOCK_EXIT_CODE
    assert third.exit_code == 0
    assert "still failing after 2 fix attempts" in third.stdout
    assert load_turn(project).attempts == 0


def test_on_stop_with_nothing_changed(project: Path) -> None:
    config = make_config(project, test_command=FAIL)

    assert on_stop(config, stop_hook(project), now=1.0).exit_code == 0


def test_on_stop_requests_reload_when_server_runs(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SERVE_RUNNING, lambda root: True)
    record_edit(project, "src/orders.py")

    outcome = on_stop(make_config(project), stop_hook(project), now=1.0)

    assert (project / ".tether" / RELOAD_REQUEST_FILE).exists()
    assert "server reloaded" in json.loads(outcome.stdout)["systemMessage"]


def test_on_stop_skips_reload_for_test_only_changes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SERVE_RUNNING, lambda root: True)
    record_edit(project, "tests/test_orders.py")

    on_stop(make_config(project), stop_hook(project), now=1.0)

    assert not (project / ".tether" / RELOAD_REQUEST_FILE).exists()


def test_check_reports_failures(project: Path) -> None:
    record_edit(project, "src/orders.py")

    outcome = check(make_config(project, lint_command=FAIL), full=False)

    assert outcome.exit_code == 1
    assert "lint failed" in outcome.stdout


def test_hooks_settings_is_valid_json() -> None:
    settings = json.loads(hooks_settings())

    assert set(settings["hooks"]) == {"UserPromptSubmit", "PostToolUse", "Stop"}


def test_hook_entrypoint_end_to_end(project: Path) -> None:
    write(project, "src/bad.py", "import os\n")
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(project / "src/bad.py")},
        }
    )

    completed = subprocess.run(
        [sys.executable, "-m", "tether", "on-edit"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=project,
    )

    assert completed.returncode == BLOCK_EXIT_CODE
    assert "F401" in completed.stderr


def test_on_edit_reports_guard_violation(project: Path) -> None:
    write(project, "src/orders.py", "print('debug')\n")
    rule = ForbiddenPattern(r"\bprint\(", "use logging", ("src/**/*.py",))
    config = make_config(project, forbid=(rule,))

    outcome = on_edit(config, edit_hook(project, "src/orders.py"))

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "src/orders.py:1: [forbid] use logging" in outcome.stderr


def test_on_stop_blocks_on_guard_violation(project: Path) -> None:
    write(project, "src/orders.py", "import fastapi\n")
    rule = ImportRule("src/**/*.py", ("fastapi",), "keep web out of core")
    config = make_config(project, imports=(rule,))
    record_edit(project, "src/orders.py")

    outcome = on_stop(config, stop_hook(project), now=1.0)

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "## guard failed" in outcome.stderr
    assert "fastapi: keep web out of core" in outcome.stderr


def test_on_stop_blocks_unsupported_claim(project: Path) -> None:
    transcript = write_transcript(project / "t.jsonl", "Done, lint is clean.")
    config = make_config(project, lint_command=("no-such-linter",))
    record_edit(project, "src/orders.py")

    outcome = on_stop(config, stop_hook(project, transcript), now=1.0)

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "tether: unsupported claims" in outcome.stderr
    assert "'lint passes'" in outcome.stderr


def test_on_stop_accepts_claim_backed_by_checks(project: Path) -> None:
    transcript = write_transcript(project / "t.jsonl", "All tests pass.")
    record_edit(project, "src/orders.py")

    outcome = on_stop(make_config(project), stop_hook(project, transcript), 1.0)

    assert outcome.exit_code == 0


def test_on_stop_claim_check_can_be_disabled(project: Path) -> None:
    transcript = write_transcript(project / "t.jsonl", "lint is clean")
    config = make_config(
        project, lint_command=("no-such-linter",), verify_claims=False
    )
    record_edit(project, "src/orders.py")

    assert on_stop(config, stop_hook(project, transcript), 1.0).exit_code == 0


def test_on_stop_warns_about_tampering(git_project: Path) -> None:
    config = make_config(git_project)
    on_prompt(config, now=0.0)
    write(git_project, "tests/test_orders.py", "")

    outcome = on_stop(config, stop_hook(git_project), now=1.0)

    assert outcome.exit_code == 0
    message = json.loads(outcome.stdout)["systemMessage"]
    assert "tether: edits to review" in message
    assert "removed 1 assertion(s)" in message


def test_on_stop_can_block_on_tampering(git_project: Path) -> None:
    config = make_config(git_project, tamper_blocks=True)
    on_prompt(config, now=0.0)
    write(git_project, "tests/test_orders.py", "")

    outcome = on_stop(config, stop_hook(git_project), now=1.0)

    assert outcome.exit_code == BLOCK_EXIT_CODE
    assert "Undo these" in outcome.stderr
