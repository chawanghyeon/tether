import subprocess
from pathlib import Path

import pytest


def git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def add_worktree(main: Path, name: str) -> Path:
    path = main.parent / name
    git(main, "worktree", "add", "-q", "-b", name, str(path))
    return path.resolve()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    (root / ".gitignore").write_text(".env\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    (root / ".env").write_text(
        "SECRET=abc\nPORT=8000\nDATABASE_URL=postgresql://localhost/app\n"
    )
    return root.resolve()
