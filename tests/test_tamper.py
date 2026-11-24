from pathlib import Path

import pytest

from tests.conftest import git
from tether.changes import snapshot_baseline
from tether.config import Config
from tether.tamper import FileDiff, find_tampering, parse_diff, turn_diff

ORIGINAL_TEST = (
    "import pytest\n\n\n"
    "def test_total():\n"
    "    assert total(2) == 4\n"
    "    assert total(0) == 0\n\n\n"
    "def test_refund():\n"
    "    assert refund(1) == 1\n"
)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    write(tmp_path, "tests/test_orders.py", ORIGINAL_TEST)
    write(tmp_path, "src/orders.py", "def total(x):\n    return x * 2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def messages(config: Config, diffs: list[FileDiff]) -> list[str]:
    return [str(finding) for finding in find_tampering(config, diffs)]


def test_parse_diff() -> None:
    text = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n+++ b/a.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/b.py b/b.py\n"
        "deleted file mode 100644\n"
        "--- a/b.py\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-gone\n"
    )

    assert parse_diff(text) == [
        FileDiff("a.py", False, ("new",), ("old",)),
        FileDiff("b.py", True, (), ("gone",)),
    ]


def test_weakened_tests_are_flagged(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    write(
        repo,
        "tests/test_orders.py",
        "import pytest\n\n\n"
        "@pytest.mark.skip(reason='flaky')\n"
        "def test_total():\n"
        "    assert total(2) == 4\n",
    )
    config = Config(root=repo)

    found = messages(config, turn_diff(config, baseline, []))

    assert found == [
        "tests/test_orders.py: removed 2 assertion(s)",
        "tests/test_orders.py: deleted test function test_refund",
        "tests/test_orders.py: added a skip or xfail marker",
    ]


def test_deleted_test_file(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    (repo / "tests/test_orders.py").unlink()
    config = Config(root=repo)

    found = messages(config, turn_diff(config, baseline, []))

    assert found == ["tests/test_orders.py: deleted a test file"]


def test_suppressions_and_swallowed_errors(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    write(
        repo,
        "src/orders.py",
        "def total(x):\n"
        "    try:\n"
        "        return x * 2  # type: ignore\n"
        "    except Exception:\n"
        "        pass\n",
    )
    config = Config(root=repo)

    found = messages(config, turn_diff(config, baseline, []))

    assert found == [
        "src/orders.py: added 1 lint/type suppression(s)",
        "src/orders.py: added an except block that swallows errors",
    ]


def test_new_untracked_files_count_when_changed(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    write(repo, "src/extra.py", "x = 1  # noqa\n")
    write(repo, "src/older.py", "y = 1  # noqa\n")
    config = Config(root=repo)

    found = messages(config, turn_diff(config, baseline, ["src/extra.py"]))

    assert found == ["src/extra.py: added 1 lint/type suppression(s)"]


def test_baseline_hides_earlier_uncommitted_work(repo: Path) -> None:
    write(repo, "src/orders.py", "x = 1  # noqa\n")
    baseline = snapshot_baseline(repo)
    write(repo, "src/orders.py", "x = 1  # noqa\ny = 2\n")
    config = Config(root=repo)

    assert messages(config, turn_diff(config, baseline, [])) == []


def test_honest_changes_are_quiet(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    write(repo, "tests/test_orders.py", ORIGINAL_TEST + "    assert 1\n")
    config = Config(root=repo)

    assert messages(config, turn_diff(config, baseline, [])) == []


def test_no_git_means_no_findings(tmp_path: Path) -> None:
    config = Config(root=tmp_path)

    assert snapshot_baseline(tmp_path) == ""
    assert turn_diff(config, "", []) == []


def test_project_in_repo_subfolder(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    project = tmp_path / "apps" / "shop"
    write(project, "tests/test_orders.py", ORIGINAL_TEST)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    baseline = snapshot_baseline(project)
    (project / "tests/test_orders.py").unlink()
    config = Config(root=project)

    found = messages(config, turn_diff(config, baseline, []))

    assert found == ["tests/test_orders.py: deleted a test file"]
