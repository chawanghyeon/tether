import os
import subprocess
from pathlib import Path

from agent_harness.changes import changed_since, git_changed


def git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def make_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    (root / ".gitignore").write_text("ignored/\n")
    (root / "old.py").write_text("a = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")


def set_mtime(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


def test_git_changed_outside_repo(tmp_path: Path) -> None:
    assert git_changed(tmp_path) is None


def test_changed_since_filters_by_turn_start(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "old.py").write_text("a = 2\n")
    (tmp_path / "before.py").write_text("")
    (tmp_path / "after.py").write_text("")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "x.py").write_text("")
    set_mtime(tmp_path / "before.py", 1_000)
    set_mtime(tmp_path / "old.py", 3_000)
    set_mtime(tmp_path / "after.py", 3_000)

    changed = changed_since(tmp_path, started_at=2_000, edited=[])

    assert changed == ["after.py", "old.py"]


def test_changed_since_includes_recorded_edits(tmp_path: Path) -> None:
    assert changed_since(tmp_path, 0, ["src/a.py"]) == ["src/a.py"]
