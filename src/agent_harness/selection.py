from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from agent_harness.config import Config

PYTHON_SUFFIX = ".py"
CONFTEST = "conftest.py"
SKIPPED_STEMS = frozenset({"__init__", "__main__"})


def is_test_file(relative: PurePosixPath, config: Config) -> bool:
    in_test_dir = any(
        relative.is_relative_to(test_dir) for test_dir in config.test_dirs
    )
    name = relative.name
    return (
        in_test_dir
        and relative.suffix == PYTHON_SUFFIX
        and (name.startswith("test_") or name.endswith("_test.py"))
    )


def select_tests(changed: Iterable[str], config: Config) -> list[str]:
    selected: set[str] = set()
    for item in changed:
        relative = PurePosixPath(item)
        if relative.suffix != PYTHON_SUFFIX:
            continue
        if is_test_file(relative, config):
            selected.add(item)
        elif relative.name == CONFTEST:
            selected.update(_tests_under(config, relative.parent))
        elif relative.stem not in SKIPPED_STEMS:
            selected.update(_tests_named_for(config, relative.stem))
    return sorted(path for path in selected if (config.root / path).is_file())


def testmon_installed(root: Path) -> bool:
    return any(root.glob(".venv/lib/python*/site-packages/testmon"))


def use_testmon(config: Config) -> bool:
    if config.selection == "testmon":
        return True
    return config.selection == "auto" and testmon_installed(config.root)


def _tests_named_for(config: Config, stem: str) -> set[str]:
    names = (f"test_{stem}.py", f"{stem}_test.py")
    return {
        path
        for test_dir in config.test_dirs
        for name in names
        for path in _relative_glob(config.root, test_dir, name)
    }


def _tests_under(config: Config, directory: PurePosixPath) -> set[str]:
    return {
        path
        for name in ("test_*.py", "*_test.py")
        for path in _relative_glob(config.root, str(directory), name)
        if is_test_file(PurePosixPath(path), config)
    }


def _relative_glob(root: Path, directory: str, pattern: str) -> list[str]:
    base = root / directory
    if not base.is_dir():
        return []
    return [path.relative_to(root).as_posix() for path in base.rglob(pattern)]
