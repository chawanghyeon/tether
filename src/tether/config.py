import dataclasses
import re
import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = "pyproject.toml"
SELECTION_MODES = ("auto", "testmon", "path")


class ConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class ForbiddenPattern:
    pattern: str
    message: str
    paths: tuple[str, ...] = ("**/*.py",)


@dataclasses.dataclass(frozen=True)
class ImportRule:
    source: str
    forbid: tuple[str, ...]
    message: str = "import crosses an architecture boundary"


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
    slot_env: dict[str, str] = dataclasses.field(default_factory=dict)
    slot_env_file: str = ".env"
    slot_setup: tuple[str, ...] = ()
    slot_teardown: tuple[str, ...] = ()
    max_slots: int = 50
    layout: tuple[str, ...] = ()
    forbid: tuple[ForbiddenPattern, ...] = ()
    imports: tuple[ImportRule, ...] = ()
    verify_claims: bool = True
    tamper_blocks: bool = False

    @property
    def has_guard_rules(self) -> bool:
        return bool(self.layout or self.forbid or self.imports)


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
    values = {name: _convert(name, value) for name, value in table.items()}
    config = Config(root=root, **values)
    if config.selection not in SELECTION_MODES:
        raise ConfigError(
            f"selection must be one of {SELECTION_MODES}, "
            f"got {config.selection!r}"
        )
    return config


def _convert(name: str, value: Any) -> Any:
    if name == "forbid":
        return tuple(_forbidden_pattern(item) for item in value)
    if name == "imports":
        return tuple(_rule(ImportRule, item, name) for item in value)
    if name == "slot_env":
        if not isinstance(value, dict):
            raise ConfigError("slot_env must be a table of strings")
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(value)
    return value


def _forbidden_pattern(item: Any) -> ForbiddenPattern:
    rule = _rule(ForbiddenPattern, item, "forbid")
    try:
        re.compile(rule.pattern)
    except re.error as error:
        message = f"bad forbid pattern {rule.pattern!r}: {error}"
        raise ConfigError(message) from error
    return rule


def _rule[T](kind: type[T], item: Any, table: str) -> T:
    if not isinstance(item, dict):
        raise ConfigError(f"each [[tool.tether.{table}]] entry must be a table")
    values = {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in item.items()
    }
    try:
        return kind(**values)
    except TypeError as error:
        message = f"bad [[tool.tether.{table}]] entry: {error}"
        raise ConfigError(message) from error
