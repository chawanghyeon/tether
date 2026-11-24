import io
import json
from pathlib import Path

from tether.hooks import parse_hook_input, relative_to_root


def test_parses_post_tool_use(tmp_path: Path) -> None:
    hook = parse_hook_input(
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "cwd": str(tmp_path),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/a.py"},
                }
            )
        ),
        Path("/elsewhere"),
    )

    assert hook.event == "PostToolUse"
    assert hook.tool_name == "Edit"
    assert hook.file_path == tmp_path / "src/a.py"


def test_parses_notebook_path(tmp_path: Path) -> None:
    hook = parse_hook_input(
        io.StringIO(
            json.dumps({"tool_input": {"notebook_path": "/abs/n.ipynb"}})
        ),
        tmp_path,
    )

    assert hook.file_path == Path("/abs/n.ipynb")
    assert hook.cwd == tmp_path


def test_parses_stop_hook_active(tmp_path: Path) -> None:
    hook = parse_hook_input(
        io.StringIO(
            json.dumps({"hook_event_name": "Stop", "stop_hook_active": True})
        ),
        tmp_path,
    )

    assert hook.stop_hook_active is True
    assert hook.file_path is None


def test_empty_input_is_allowed(tmp_path: Path) -> None:
    hook = parse_hook_input(io.StringIO(""), tmp_path)

    assert hook.event == ""
    assert hook.cwd == tmp_path


def test_relative_to_root(tmp_path: Path) -> None:
    assert relative_to_root(tmp_path / "src/a.py", tmp_path) == "src/a.py"
    assert relative_to_root(Path("/outside/a.py"), tmp_path) is None


def test_parses_transcript_path(tmp_path: Path) -> None:
    hook = parse_hook_input(
        io.StringIO(json.dumps({"transcript_path": "~/t.jsonl"})), tmp_path
    )

    assert hook.transcript_path == Path("~/t.jsonl").expanduser()
