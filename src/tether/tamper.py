import dataclasses
import re
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from tether.changes import git_output
from tether.config import Config
from tether.selection import is_test_file

PYTHON_SUFFIX = ".py"
DIFF_HEADER = re.compile(r"^diff --git a/.* b/(.*)$")
TEST_SKIP = re.compile(
    r"@pytest\.mark\.(?:skip|skipif|xfail)\b"
    r"|\bpytest\.(?:skip|xfail)\("
    r"|@unittest\.skip"
)
SUPPRESSION = re.compile(r"#\s*(?:type:\s*ignore|noqa|pyright:\s*ignore)")
ASSERTION = re.compile(
    r"^\s*(?:assert\b|self\.assert\w*\(|with pytest\.raises\()"
)
TEST_FUNCTION = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)")
SWALLOWED_ERROR = re.compile(
    r"^\s*except\b[^\n]*:\s*\n\s*(?:pass|\.\.\.)\s*$", re.MULTILINE
)


@dataclasses.dataclass(frozen=True)
class FileDiff:
    path: str
    deleted: bool = False
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def parse_diff(text: str) -> list[FileDiff]:
    diffs: list[FileDiff] = []
    path: str | None = None
    deleted = False
    added: list[str] = []
    removed: list[str] = []

    def flush() -> None:
        if path is not None:
            diffs.append(FileDiff(path, deleted, tuple(added), tuple(removed)))

    for line in text.splitlines():
        header = DIFF_HEADER.match(line)
        if header:
            flush()
            path, deleted, added, removed = header.group(1), False, [], []
        elif line.startswith("deleted file mode"):
            deleted = True
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    flush()
    return diffs


def turn_diff(
    config: Config, baseline: str, changed: Iterable[str]
) -> list[FileDiff]:
    output = git_output(
        config.root,
        "diff",
        "--unified=0",
        "--no-color",
        "--no-renames",
        "--relative",
        baseline or "HEAD",
    )
    if output is None:
        return []
    diffs = parse_diff(output)
    known = {diff.path for diff in diffs}
    untracked = git_output(
        config.root, "ls-files", "--others", "--exclude-standard"
    )
    new_files = set((untracked or "").splitlines()) & set(changed)
    for path in sorted(new_files - known):
        try:
            lines = (config.root / path).read_text().splitlines()
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        diffs.append(FileDiff(path, added=tuple(lines)))
    return diffs


def find_tampering(config: Config, diffs: Sequence[FileDiff]) -> list[Finding]:
    findings = []
    for diff in diffs:
        if not diff.path.endswith(PYTHON_SUFFIX):
            continue
        if is_test_file(PurePosixPath(diff.path), config):
            findings.extend(_test_findings(diff))
        suppressions = sum(
            bool(SUPPRESSION.search(line)) for line in diff.added
        )
        if suppressions:
            findings.append(
                Finding(
                    diff.path, f"added {suppressions} lint/type suppression(s)"
                )
            )
        if SWALLOWED_ERROR.search("\n".join(diff.added)):
            findings.append(
                Finding(diff.path, "added an except block that swallows errors")
            )
    return findings


def _test_findings(diff: FileDiff) -> list[Finding]:
    if diff.deleted:
        return [Finding(diff.path, "deleted a test file")]
    findings = []
    lost = _count(ASSERTION, diff.removed) - _count(ASSERTION, diff.added)
    if lost > 0:
        findings.append(Finding(diff.path, f"removed {lost} assertion(s)"))
    removed_tests = _test_names(diff.removed) - _test_names(diff.added)
    findings.extend(
        Finding(diff.path, f"deleted test function {name}")
        for name in sorted(removed_tests)
    )
    if any(TEST_SKIP.search(line) for line in diff.added):
        findings.append(Finding(diff.path, "added a skip or xfail marker"))
    return findings


def _count(pattern: re.Pattern[str], lines: Iterable[str]) -> int:
    return sum(bool(pattern.search(line)) for line in lines)


def _test_names(lines: Iterable[str]) -> set[str]:
    return {
        match.group(1) for line in lines if (match := TEST_FUNCTION.match(line))
    }
