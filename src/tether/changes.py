import subprocess
from collections.abc import Iterable
from pathlib import Path

GIT_CHANGED_COMMAND = (
    "git",
    "ls-files",
    "--modified",
    "--others",
    "--exclude-standard",
    "-z",
)


def git_changed(root: Path) -> list[str] | None:
    try:
        completed = subprocess.run(
            GIT_CHANGED_COMMAND, cwd=root, capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    return [item for item in completed.stdout.split("\0") if item]


def changed_since(
    root: Path, started_at: float, edited: Iterable[str]
) -> list[str]:
    candidates = set(edited)
    for path in git_changed(root) or []:
        if _modified_after(root / path, started_at):
            candidates.add(path)
    return sorted(candidates)


def _modified_after(path: Path, started_at: float) -> bool:
    try:
        return path.stat().st_mtime >= started_at
    except FileNotFoundError:
        return False
