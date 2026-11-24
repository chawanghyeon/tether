import dataclasses
import json
from pathlib import Path
from typing import Any, TextIO

FILE_PATH_KEYS = ("file_path", "notebook_path")
BLOCK_EXIT_CODE = 2


@dataclasses.dataclass(frozen=True)
class HookInput:
    event: str
    cwd: Path
    tool_name: str | None = None
    file_path: Path | None = None
    stop_hook_active: bool = False


def parse_hook_input(stream: TextIO, fallback_cwd: Path) -> HookInput:
    text = stream.read().strip()
    raw: dict[str, Any] = json.loads(text) if text else {}
    cwd = Path(raw.get("cwd") or fallback_cwd)
    tool_input = raw.get("tool_input") or {}
    return HookInput(
        event=str(raw.get("hook_event_name", "")),
        cwd=cwd,
        tool_name=raw.get("tool_name"),
        file_path=_file_path(tool_input, cwd),
        stop_hook_active=bool(raw.get("stop_hook_active", False)),
    )


def relative_to_root(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def system_message(text: str) -> str:
    return json.dumps({"systemMessage": text})


def _file_path(tool_input: dict[str, Any], cwd: Path) -> Path | None:
    for key in FILE_PATH_KEYS:
        value = tool_input.get(key)
        if value:
            path = Path(value)
            return path if path.is_absolute() else cwd / path
    return None
