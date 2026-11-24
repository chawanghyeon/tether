import ast
import dataclasses
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from tether.changes import git_output
from tether.config import Config
from tether.tamper import FileDiff

PYTHON_SUFFIX = ".py"
SUMMARY_FILE = "summary.md"
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


@dataclasses.dataclass(frozen=True)
class Symbols:
    signatures: dict[str, str]
    imports: frozenset[str]


@dataclasses.dataclass(frozen=True)
class FileChange:
    path: str
    status: str
    lines_added: int
    lines_removed: int
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    new_imports: tuple[str, ...] = ()


def extract_symbols(text: str) -> Symbols | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    signatures: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signatures[node.name] = _signature(node)
        elif isinstance(node, ast.ClassDef):
            signatures[node.name] = f"class {node.name}"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{node.name}.{item.name}"
                    signatures[name] = _signature(item, name)
    return Symbols(signatures, frozenset(_imports(tree)))


def summarize_changes(
    config: Config, baseline: str, diffs: Sequence[FileDiff]
) -> list[FileChange]:
    local = _local_packages(config)
    changes = []
    for diff in sorted(diffs, key=lambda item: item.path):
        old = _old_text(config.root, baseline, diff.path)
        new_file = config.root / diff.path
        new = (
            None if diff.deleted or not new_file.is_file() else _read(new_file)
        )
        status = (
            "deleted" if new is None else "added" if old is None else "modified"
        )
        change = FileChange(
            diff.path, status, len(diff.added), len(diff.removed)
        )
        if diff.path.endswith(PYTHON_SUFFIX):
            change = _with_symbols(change, old, new, local)
        changes.append(change)
    return changes


def render_markdown(changes: Sequence[FileChange]) -> str:
    if not changes:
        return "# tether summary\n\nNo changes.\n"
    lines = ["# tether summary", "", one_line(changes), ""]
    for group, members in _grouped(changes):
        lines.append(f"## {group}")
        for change in members:
            name = PurePosixPath(change.path).name
            lines.append(
                f"- `{name}` {change.status} "
                f"(+{change.lines_added} -{change.lines_removed})"
            )
            lines.extend(_detail("added", change.added))
            lines.extend(_detail("removed", change.removed))
            lines.extend(_detail("changed", change.changed))
            lines.extend(_detail("new import", change.new_imports))
        lines.append("")
    return "\n".join(lines)


def one_line(changes: Sequence[FileChange]) -> str:
    added = sum(change.lines_added for change in changes)
    removed = sum(change.lines_removed for change in changes)
    parts = [f"{len(changes)} file(s) (+{added} -{removed})"]
    counts = (
        ("added", sum(len(change.added) for change in changes)),
        ("removed", sum(len(change.removed) for change in changes)),
        ("changed", sum(len(change.changed) for change in changes)),
    )
    parts.extend(
        f"{count} symbol(s) {label}" for label, count in counts if count
    )
    imports = sorted(
        {name for change in changes for name in change.new_imports}
    )
    if imports:
        parts.append("new imports: " + ", ".join(imports))
    return "tether: " + ", ".join(parts)


def write_summary(state_directory: Path, changes: Sequence[FileChange]) -> Path:
    path = state_directory / SUMMARY_FILE
    path.write_text(render_markdown(changes))
    return path


def _with_symbols(
    change: FileChange, old: str | None, new: str | None, local: set[str]
) -> FileChange:
    before = (
        extract_symbols(old) if old is not None else Symbols({}, frozenset())
    )
    after = (
        extract_symbols(new) if new is not None else Symbols({}, frozenset())
    )
    if before is None or after is None:
        return change
    old_names, new_names = set(before.signatures), set(after.signatures)
    return dataclasses.replace(
        change,
        added=tuple(
            after.signatures[name] for name in sorted(new_names - old_names)
        ),
        removed=tuple(sorted(old_names - new_names)),
        changed=tuple(
            f"{before.signatures[name]} -> {after.signatures[name]}"
            for name in sorted(old_names & new_names)
            if before.signatures[name] != after.signatures[name]
        ),
        new_imports=tuple(
            sorted(
                name
                for name in after.imports - before.imports
                if name not in STDLIB and name not in local
            )
        ),
    )


def _signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef, name: str | None = None
) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{name or node.name}({ast.unparse(node.args)}){returns}"


def _imports(tree: ast.Module) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif (
            isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
        ):
            yield node.module.split(".")[0]


def _local_packages(config: Config) -> set[str]:
    names = set()
    for source_dir in (*config.source_dirs, *config.test_dirs, "."):
        base = config.root / source_dir
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
            elif child.suffix == PYTHON_SUFFIX:
                names.add(child.stem)
    return names


def _old_text(root: Path, baseline: str, path: str) -> str | None:
    return git_output(root, "show", f"{baseline or 'HEAD'}:./{path}")


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return ""


def _grouped(
    changes: Sequence[FileChange],
) -> list[tuple[str, list[FileChange]]]:
    groups: dict[str, list[FileChange]] = {}
    for change in changes:
        parent = PurePosixPath(change.path).parent.as_posix()
        groups.setdefault(parent if parent != "." else "(root)", []).append(
            change
        )
    return sorted(groups.items())


def _detail(label: str, items: Sequence[str]) -> list[str]:
    return [f"  - {label}: `{item}`" for item in items]
