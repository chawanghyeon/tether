from pathlib import Path

from tether.checks import (
    CheckResult,
    Deadline,
    Status,
    failed,
    format_report,
    run_check,
    run_turn_checks,
)
from tether.config import Config


def python_exit(code: int, message: str = "") -> tuple[str, ...]:
    script = f"import sys; print({message!r}); sys.exit({code})"
    return ("python", "-c", script)


def write(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_run_check_passes_and_fails(tmp_path: Path) -> None:
    passed = run_check("ok", python_exit(0), tmp_path, timeout=10)
    broken = run_check("bad", python_exit(1, "boom"), tmp_path, timeout=10)

    assert passed.status is Status.PASSED
    assert broken.status is Status.FAILED
    assert broken.output == "boom"


def test_run_check_skips_missing_tool(tmp_path: Path) -> None:
    result = run_check("x", ("no-such-tool-xyz",), tmp_path, timeout=10)

    assert result.status is Status.SKIPPED


def test_run_check_times_out(tmp_path: Path) -> None:
    sleeper = ("python", "-c", "import time; time.sleep(5)")

    result = run_check("slow", sleeper, tmp_path, timeout=0.2)

    assert result.status is Status.TIMED_OUT


def test_run_check_with_empty_budget(tmp_path: Path) -> None:
    result = run_check("x", python_exit(0), tmp_path, timeout=0)

    assert result.status is Status.TIMED_OUT


def test_turn_checks_ignore_non_python(tmp_path: Path) -> None:
    write(tmp_path, "README.md")
    config = Config(root=tmp_path)

    assert run_turn_checks(config, ["README.md"], Deadline.after(10)) == []


def test_turn_checks_run_only_related_tests(tmp_path: Path) -> None:
    write(tmp_path, "src/orders.py")
    write(tmp_path, "tests/test_orders.py")
    record = "import sys; print(' '.join(sys.argv[1:]))"
    config = Config(
        root=tmp_path,
        lint_command=python_exit(0),
        typecheck_command=python_exit(0),
        test_command=("python", "-c", record),
    )

    results = run_turn_checks(config, ["src/orders.py"], Deadline.after(10))

    assert [r.status for r in results] == [Status.PASSED] * 3
    assert results[2].output == "tests/test_orders.py"


def test_turn_checks_skip_tests_without_matches(tmp_path: Path) -> None:
    write(tmp_path, "src/lonely.py")
    config = Config(
        root=tmp_path,
        lint_command=python_exit(0),
        typecheck_command=python_exit(0),
    )

    results = run_turn_checks(config, ["src/lonely.py"], Deadline.after(10))

    assert results[2].status is Status.SKIPPED
    assert results[2].output == "no related tests"


def test_turn_checks_with_real_ruff(tmp_path: Path) -> None:
    write(tmp_path, "src/bad.py", "import os\n")
    config = Config(root=tmp_path, typecheck_command=python_exit(0))

    results = run_turn_checks(config, ["src/bad.py"], Deadline.after(30))

    assert results[0].status is Status.FAILED
    assert "F401" in results[0].output


def test_failed_filters_failures() -> None:
    results = [
        CheckResult("a", Status.PASSED),
        CheckResult("b", Status.FAILED),
        CheckResult("c", Status.TIMED_OUT),
    ]

    assert failed(results) == [results[1]]


def test_format_report_truncates_long_output() -> None:
    results = [
        CheckResult("lint", Status.PASSED, "ignored", 0.1),
        CheckResult("tests", Status.FAILED, "x" * 50 + "END", 1.0),
    ]

    report = format_report(results, max_chars=10)

    assert report.startswith("tether: lint passed (0.1s), tests failed")
    assert "ignored" not in report
    assert report.endswith("... (truncated)\nxxxxxxxEND")
