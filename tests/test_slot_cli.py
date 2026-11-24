import dataclasses
from pathlib import Path
from typing import Any

from tests.conftest import add_worktree
from tether.config import Config
from tether.slot_cli import slot_command

RECORD = (
    "python",
    "-c",
    "import os, sys; open(sys.argv[1], 'w').write(os.environ['PORT'])",
)


def config_for(root: Path, **overrides: Any) -> Config:
    base = Config(root=root, slot_env={"PORT": "{8000 + slot}"})
    return dataclasses.replace(base, **overrides)


def test_show_before_setup_fails(main_repo: Path) -> None:
    config = config_for(add_worktree(main_repo, "wt-a"))

    assert slot_command(config, "show", force=False).exit_code == 1


def test_setup_writes_env_and_runs_command(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    marker = worktree / "setup.out"
    config = config_for(worktree, slot_setup=(*RECORD, str(marker)))

    outcome = slot_command(config, "setup", force=False)

    assert outcome.exit_code == 0
    assert "slot 1" in outcome.stdout
    assert "PORT=8001" in (worktree / ".env").read_text()
    assert marker.read_text() == "8001"
    assert "PORT=8001" in slot_command(config, "show", force=False).stdout


def test_failed_setup_is_reported(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    failing = ("python", "-c", "import sys; print('db down'); sys.exit(3)")
    config = config_for(worktree, slot_setup=failing)

    outcome = slot_command(config, "setup", force=False)

    assert outcome.exit_code == 1
    assert "db down" in outcome.stderr


def test_teardown_runs_command_and_releases(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    marker = worktree / "teardown.out"
    config = config_for(worktree, slot_teardown=(*RECORD, str(marker)))
    slot_command(config, "setup", force=False)

    outcome = slot_command(config, "teardown", force=False)

    assert outcome.exit_code == 0
    assert marker.read_text() == "8001"
    assert slot_command(config, "show", force=False).exit_code == 1


def test_teardown_refuses_main(main_repo: Path) -> None:
    outcome = slot_command(config_for(main_repo), "teardown", force=False)

    assert outcome.exit_code == 1


def test_doctor_after_setup_is_clean(main_repo: Path) -> None:
    config = config_for(add_worktree(main_repo, "wt-a"))
    slot_command(config, "setup", force=False)

    outcome = slot_command(config, "doctor", force=False)

    assert outcome.exit_code == 0


def test_slot_errors_become_messages(tmp_path: Path) -> None:
    outcome = slot_command(config_for(tmp_path), "setup", force=False)

    assert outcome.exit_code == 1
    assert outcome.stderr.startswith("tether slot:")
