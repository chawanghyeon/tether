import re
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
HUNK_HEADER = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


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


def is_untracked(root: Path, path: str) -> bool:
    output = git_output(
        root, "ls-files", "--others", "--exclude-standard", "--", path
    )
    return bool(output and output.strip())


def added_lines(root: Path, path: str) -> set[int] | None:
    if is_untracked(root, path):
        return None
    output = git_output(root, "diff", "--unified=0", "HEAD", "--", path)
    if output is None:
        return None
    lines: set[int] = set()
    for match in HUNK_HEADER.finditer(output):
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        lines.update(range(start, start + count))
    return lines


def git_output(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *args), cwd=root, capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    return completed.stdout if completed.returncode == 0 else None


def snapshot_baseline(root: Path) -> str:
    stash = git_output(root, "stash", "create")
    if stash and stash.strip():
        return stash.strip()
    head = git_output(root, "rev-parse", "--verify", "HEAD")
    return head.strip() if head else ""
