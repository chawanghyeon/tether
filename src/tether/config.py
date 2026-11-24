import dataclasses
import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = "pyproject.toml"
SELECTION_MODES = ("auto", "testmon", "path")


class ConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Config:
    root: Path
    source_dirs: tuple[str, ...] = ("src",)
    test_dirs: tuple[str, ...] = ("tests",)
    lint_command: tuple[str, ...] = ("ruff", "check", "--quiet")
    typecheck_command: tuple[str, ...] = ("pyright",)
    test_command: tuple[str, ...] = ("pytest", "-q")
    selection: str = "auto"
    lint_on_edit: bool = True
    max_stop_attempts: int = 2
    stop_timeout_seconds: float = 60.0
    reload_globs: tuple[str, ...] = ("src/**/*.py",)
    max_report_chars: int = 4000


def find_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / PYPROJECT).is_file():
            return candidate
    return start


def load_config(root: Path) -> Config:
    pyproject = root / PYPROJECT
    table: dict[str, Any] = {}
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text())
        table = data.get("tool", {}).get("tether", {})
    return _build(root, table)


def _build(root: Path, table: dict[str, Any]) -> Config:
    fields = {f.name: f for f in dataclasses.fields(Config) if f.name != "root"}
    unknown = sorted(set(table) - set(fields))
    if unknown:
        raise ConfigError(f"unknown [tool.tether] keys: {', '.join(unknown)}")
    values: dict[str, Any] = {
        name: tuple(value) if isinstance(value, list) else value
        for name, value in table.items()
    }
    config = Config(root=root, **values)
    if config.selection not in SELECTION_MODES:
        raise ConfigError(
            f"selection must be one of {SELECTION_MODES}, "
            f"got {config.selection!r}"
        )
    return config
