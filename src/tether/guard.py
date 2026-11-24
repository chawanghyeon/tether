import ast
import dataclasses
import re
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from tether.changes import added_lines, is_untracked
from tether.checks import CheckResult, Status
from tether.config import Config

PYTHON_SUFFIX = ".py"
INIT_STEM = "__init__"


@dataclasses.dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def guard_file(config: Config, path: str) -> list[Violation]:
    file = config.root / path
    if not file.is_file():
        return []
    violations = _check_layout(config, path)
    lines = added_lines(config.root, path)
    try:
        text = file.read_text()
    except UnicodeDecodeError:
        return violations
    violations.extend(_check_forbidden(config, path, text, lines))
    if path.endswith(PYTHON_SUFFIX):
        violations.extend(_check_imports(config, path, text, lines))
    return violations


def guard_files(config: Config, paths: Iterable[str]) -> list[Violation]:
    return [
        violation for path in paths for violation in guard_file(config, path)
    ]


def guard_check(config: Config, paths: Sequence[str]) -> CheckResult | None:
    if not config.has_guard_rules:
        return None
    violations = guard_files(config, paths)
    if not violations:
        return CheckResult("guard", Status.PASSED)
    output = "\n".join(str(violation) for violation in violations)
    return CheckResult("guard", Status.FAILED, output)


def module_name(config: Config, path: str) -> str | None:
    relative = PurePosixPath(path)
    for source_dir in (*config.source_dirs, ""):
        if source_dir and not relative.is_relative_to(source_dir):
            continue
        inner = relative.relative_to(source_dir) if source_dir else relative
        parts = list(inner.with_suffix("").parts)
        if parts and parts[-1] == INIT_STEM:
            parts.pop()
        return ".".join(parts) or None
    return None


def _check_layout(config: Config, path: str) -> list[Violation]:
    if not config.layout or not path.endswith(PYTHON_SUFFIX):
        return []
    if not is_untracked(config.root, path):
        return []
    relative = PurePosixPath(path)
    if any(relative.full_match(pattern) for pattern in config.layout):
        return []
    allowed = ", ".join(config.layout)
    return [
        Violation(
            path, 1, "layout", f"new file outside allowed paths ({allowed})"
        )
    ]


def _check_forbidden(
    config: Config, path: str, text: str, lines: set[int] | None
) -> list[Violation]:
    relative = PurePosixPath(path)
    violations = []
    for rule in config.forbid:
        if not any(relative.full_match(pattern) for pattern in rule.paths):
            continue
        expression = re.compile(rule.pattern)
        for number, line in enumerate(text.splitlines(), start=1):
            if (lines is None or number in lines) and expression.search(line):
                violations.append(
                    Violation(path, number, "forbid", rule.message)
                )
    return violations


def _check_imports(
    config: Config, path: str, text: str, lines: set[int] | None
) -> list[Violation]:
    relative = PurePosixPath(path)
    rules = [
        rule for rule in config.imports if relative.full_match(rule.source)
    ]
    if not rules:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    package = _package_of(config, path)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if lines is not None and node.lineno not in lines:
            continue
        for imported in _imported_modules(node, package):
            for rule in rules:
                if any(_within(imported, prefix) for prefix in rule.forbid):
                    violations.append(
                        Violation(
                            path,
                            node.lineno,
                            "imports",
                            f"{imported}: {rule.message}",
                        )
                    )
    return violations


def _package_of(config: Config, path: str) -> list[str]:
    name = module_name(config, path) or ""
    parts = name.split(".") if name else []
    if PurePosixPath(path).stem != INIT_STEM and parts:
        parts.pop()
    return parts


def _imported_modules(
    node: ast.Import | ast.ImportFrom, package: list[str]
) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level == 0:
        base = node.module or ""
    else:
        anchor = package[: len(package) - (node.level - 1)]
        base = ".".join([*anchor, *([node.module] if node.module else [])])
    if node.module:
        return [base]
    return [
        f"{base}.{alias.name}" if base else alias.name for alias in node.names
    ]


def _within(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")
