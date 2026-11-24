from pathlib import Path

import pytest

from tests.conftest import git
from tether.checks import Status
from tether.config import Config, ForbiddenPattern, ImportRule
from tether.guard import guard_check, guard_file, module_name

DOMAIN_RULE = ImportRule(
    "src/app/domain/**/*.py",
    ("app.api", "fastapi"),
    "domain must not import outer layers",
)
PRINT_RULE = ForbiddenPattern(r"\bprint\(", "use logging", ("src/**/*.py",))


def write(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    write(tmp_path, "src/app/domain/orders.py", "print('legacy')\n")
    write(tmp_path, "src/app/api/routes.py", "")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def rules(root: Path) -> Config:
    return Config(
        root=root,
        layout=("src/**/*.py", "tests/**/*.py"),
        forbid=(PRINT_RULE,),
        imports=(DOMAIN_RULE,),
    )


def test_module_name() -> None:
    config = Config(root=Path("/x"))

    assert (
        module_name(config, "src/app/domain/orders.py") == "app.domain.orders"
    )
    assert module_name(config, "src/app/__init__.py") == "app"
    assert module_name(config, "scripts/tool.py") == "scripts.tool"


def test_new_file_outside_layout(repo: Path) -> None:
    write(repo, "app_utils.py", "x = 1\n")

    violations = guard_file(rules(repo), "app_utils.py")

    assert [v.rule for v in violations] == ["layout"]


def test_new_file_inside_layout(repo: Path) -> None:
    write(repo, "tests/test_new.py", "x = 1\n")

    assert guard_file(rules(repo), "tests/test_new.py") == []


def test_forbid_only_flags_added_lines(repo: Path) -> None:
    write(
        repo,
        "src/app/domain/orders.py",
        "print('legacy')\nx = 1\nprint('new')\n",
    )

    violations = guard_file(rules(repo), "src/app/domain/orders.py")

    assert [(v.line, v.rule) for v in violations] == [(3, "forbid")]
    assert str(violations[0]) == (
        "src/app/domain/orders.py:3: [forbid] use logging"
    )


def test_forbid_respects_paths(repo: Path) -> None:
    write(repo, "tests/test_x.py", "print('debug')\n")

    assert guard_file(rules(repo), "tests/test_x.py") == []


def test_imports_absolute_and_relative(repo: Path) -> None:
    write(
        repo,
        "src/app/domain/orders.py",
        "print('legacy')\n"
        "import fastapi\n"
        "from app.api.routes import router\n"
        "from ..api import routes\n"
        "from . import models\n"
        "import json\n",
    )

    violations = guard_file(rules(repo), "src/app/domain/orders.py")

    flagged = [(v.line, v.message.split(":")[0]) for v in violations]
    assert flagged == [
        (2, "fastapi"),
        (3, "app.api.routes"),
        (4, "app.api"),
    ]


def test_imports_outside_rule_source_are_fine(repo: Path) -> None:
    write(repo, "src/app/api/routes.py", "import fastapi\n")

    assert guard_file(rules(repo), "src/app/api/routes.py") == []


def test_syntax_errors_are_left_to_lint(repo: Path) -> None:
    write(repo, "src/app/domain/broken.py", "def (:\n")

    assert guard_file(rules(repo), "src/app/domain/broken.py") == []


def test_guard_check_skipped_without_rules(repo: Path) -> None:
    assert guard_check(Config(root=repo), ["src/app/api/routes.py"]) is None


def test_guard_check_reports_violations(repo: Path) -> None:
    write(repo, "loose.py", "")

    result = guard_check(rules(repo), ["loose.py", "missing.py"])

    assert result is not None
    assert result.status is Status.FAILED
    assert "loose.py:1: [layout]" in result.output
