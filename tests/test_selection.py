from pathlib import Path, PurePosixPath

import pytest

from agent_harness.config import Config
from agent_harness.selection import is_test_file, select_tests, use_testmon


def touch(root: Path, *relative: str) -> None:
    for item in relative:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


@pytest.fixture
def project(tmp_path: Path) -> Config:
    touch(
        tmp_path,
        "src/shop/orders.py",
        "src/shop/__init__.py",
        "tests/shop/test_orders.py",
        "tests/shop/conftest.py",
        "tests/shop/test_refunds.py",
        "tests/api/orders_test.py",
        "tests/test_other.py",
    )
    return Config(root=tmp_path)


def test_is_test_file(project: Config) -> None:
    assert is_test_file(PurePosixPath("tests/a/test_x.py"), project)
    assert is_test_file(PurePosixPath("tests/x_test.py"), project)
    assert not is_test_file(PurePosixPath("tests/conftest.py"), project)
    assert not is_test_file(PurePosixPath("src/test_x.py"), project)


def test_source_file_maps_to_tests_by_name(project: Config) -> None:
    assert select_tests(["src/shop/orders.py"], project) == [
        "tests/api/orders_test.py",
        "tests/shop/test_orders.py",
    ]


def test_changed_test_file_selects_itself(project: Config) -> None:
    assert select_tests(["tests/test_other.py"], project) == [
        "tests/test_other.py"
    ]


def test_conftest_selects_tests_in_its_directory(project: Config) -> None:
    assert select_tests(["tests/shop/conftest.py"], project) == [
        "tests/shop/test_orders.py",
        "tests/shop/test_refunds.py",
    ]


def test_ignores_init_and_non_python(project: Config) -> None:
    assert select_tests(["src/shop/__init__.py", "README.md"], project) == []


def test_deleted_test_file_is_dropped(project: Config) -> None:
    assert select_tests(["tests/gone/test_gone.py"], project) == []


def test_use_testmon_auto_detects_install(tmp_path: Path) -> None:
    config = Config(root=tmp_path)
    assert not use_testmon(config)

    (tmp_path / ".venv/lib/python3.13/site-packages/testmon").mkdir(
        parents=True
    )

    assert use_testmon(config)
    assert not use_testmon(Config(root=tmp_path, selection="path"))
