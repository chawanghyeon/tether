from collections.abc import Sequence

from tether.checks import CheckResult, Deadline, run_check, run_turn_checks
from tether.config import Config
from tether.guard import guard_check

EDIT_LINT_TIMEOUT_SECONDS = 10.0
PYTHON_SUFFIX = ".py"


def edit_results(config: Config, path: str) -> list[CheckResult]:
    results = _guard(config, [path])
    if config.lint_on_edit and path.endswith(PYTHON_SUFFIX):
        results.append(
            run_check(
                "lint",
                (*config.lint_command, path),
                config.root,
                EDIT_LINT_TIMEOUT_SECONDS,
            )
        )
    return results


def turn_results(
    config: Config, changed: Sequence[str], deadline: Deadline
) -> list[CheckResult]:
    return _guard(config, changed) + run_turn_checks(config, changed, deadline)


def _guard(config: Config, paths: Sequence[str]) -> list[CheckResult]:
    result = guard_check(config, paths)
    return [] if result is None else [result]
