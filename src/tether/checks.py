import dataclasses
import enum
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from tether.config import Config
from tether.selection import select_tests, use_testmon

PYTEST_NO_TESTS_COLLECTED = 5
PYTHON_SUFFIX = ".py"
TRUNCATION_MARKER = "... (truncated)\n"


class Status(enum.StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed out"


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    output: str = ""
    seconds: float = 0.0


@dataclasses.dataclass(frozen=True)
class Deadline:
    expires_at: float | None

    @classmethod
    def after(cls, seconds: float | None) -> "Deadline":
        if seconds is None:
            return cls(None)
        return cls(time.monotonic() + seconds)

    def remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.monotonic())


def resolve_executable(root: Path, name: str) -> str | None:
    local = root / ".venv" / "bin" / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


def run_check(
    name: str,
    command: Sequence[str],
    root: Path,
    timeout: float | None,
    ok_codes: Sequence[int] = (0,),
) -> CheckResult:
    if timeout is not None and timeout <= 0:
        return CheckResult(name, Status.TIMED_OUT, "no time left in budget")
    executable = resolve_executable(root, command[0])
    if executable is None:
        return CheckResult(name, Status.SKIPPED, f"{command[0]} not found")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name,
            Status.TIMED_OUT,
            f"exceeded {timeout:.0f}s",
            time.monotonic() - started,
        )
    output = (completed.stdout + completed.stderr).strip()
    status = (
        Status.PASSED if completed.returncode in ok_codes else Status.FAILED
    )
    return CheckResult(name, status, output, time.monotonic() - started)


def run_turn_checks(
    config: Config, changed: Sequence[str], deadline: Deadline
) -> list[CheckResult]:
    python_files = [
        path
        for path in changed
        if path.endswith(PYTHON_SUFFIX) and (config.root / path).is_file()
    ]
    if not python_files:
        return []
    results = [
        run_check(
            "lint",
            (*config.lint_command, *python_files),
            config.root,
            deadline.remaining(),
        ),
        run_check(
            "typecheck",
            (*config.typecheck_command, *python_files),
            config.root,
            deadline.remaining(),
        ),
    ]
    if use_testmon(config):
        test_command = (*config.test_command, "--testmon")
    else:
        selected = select_tests(changed, config)
        if not selected:
            results.append(
                CheckResult("tests", Status.SKIPPED, "no related tests")
            )
            return results
        test_command = (*config.test_command, *selected)
    results.append(
        run_check(
            "tests",
            test_command,
            config.root,
            deadline.remaining(),
            ok_codes=(0, PYTEST_NO_TESTS_COLLECTED),
        )
    )
    return results


def run_full_checks(config: Config) -> list[CheckResult]:
    return [
        run_check("lint", (*config.lint_command, "."), config.root, None),
        run_check("typecheck", config.typecheck_command, config.root, None),
        run_check(
            "tests",
            config.test_command,
            config.root,
            None,
            ok_codes=(0, PYTEST_NO_TESTS_COLLECTED),
        ),
    ]


def failed(results: Sequence[CheckResult]) -> list[CheckResult]:
    return [result for result in results if result.status is Status.FAILED]


def summarize(results: Sequence[CheckResult]) -> str:
    parts = [
        f"{result.name} {result.status} ({result.seconds:.1f}s)"
        for result in results
    ]
    return "tether: " + (", ".join(parts) if parts else "nothing to check")


def format_report(results: Sequence[CheckResult], max_chars: int) -> str:
    sections = [summarize(results)]
    for result in results:
        if result.status in (Status.FAILED, Status.TIMED_OUT):
            sections.append(
                f"## {result.name} {result.status}\n"
                f"{_tail(result.output, max_chars)}"
            )
    return "\n\n".join(sections)


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return TRUNCATION_MARKER + text[-max_chars:]
