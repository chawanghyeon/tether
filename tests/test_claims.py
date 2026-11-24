import json
from pathlib import Path
from typing import Any

from tether.checks import CheckResult, Status
from tether.claims import (
    CommandRun,
    TurnTranscript,
    read_turn,
    unsupported_claims,
)

EARLY = "2026-01-01T00:00:00.000Z"
LATE = "2026-01-01T00:10:00.000Z"
BETWEEN = 1767226000.0


def user(content: Any, timestamp: str = LATE) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {"role": "user", "content": content},
    }


def assistant(*blocks: dict[str, Any], timestamp: str = LATE) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {"role": "assistant", "content": list(blocks)},
    }


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def bash(tool_id: str, command: str) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Bash",
        "input": {"command": command},
    }


def result(tool_id: str, output: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": output,
        "is_error": is_error,
    }


def write_transcript(path: Path, entries: list[dict[str, Any]]) -> Path:
    lines = [json.dumps(entry) for entry in entries]
    path.write_text("\n".join([*lines, "not json"]) + "\n")
    return path


def turn(final: str, *runs: CommandRun) -> TurnTranscript:
    return TurnTranscript(final, runs)


def test_read_turn_starts_at_last_prompt(tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        [
            user("first prompt"),
            assistant(bash("old", "pytest")),
            user([result("old", "1 passed")]),
            user("second prompt"),
            assistant(text("working"), bash("a", "uv run pytest -q")),
            user([result("a", [text("3 passed")])]),
            assistant(text("Done. All tests pass.")),
        ],
    )

    parsed = read_turn(transcript)

    assert parsed.final_text == "Done. All tests pass."
    assert parsed.runs == (CommandRun("uv run pytest -q", "3 passed", False),)


def test_read_turn_uses_timestamp_when_known(tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        [
            user("prompt", timestamp=EARLY),
            assistant(bash("a", "pytest"), timestamp=EARLY),
            user([result("a", "ok")], timestamp=EARLY),
            user("hook feedback that looks like a prompt"),
            assistant(bash("b", "ruff check")),
            user([result("b", "Found 1 error.", is_error=True)]),
        ],
    )

    parsed = read_turn(transcript, since=BETWEEN)

    assert [run.command for run in parsed.runs] == ["ruff check"]


def test_missing_transcript_is_empty(tmp_path: Path) -> None:
    assert read_turn(tmp_path / "missing.jsonl") == TurnTranscript("", ())


def test_claim_without_any_run() -> None:
    issues = unsupported_claims(turn("Fixed it, tests pass."), [])

    assert issues == [
        "you said 'tests pass', but nothing checked that this turn"
    ]


def test_claim_after_failed_run() -> None:
    run = CommandRun("pytest -q", "1 failed, 4 passed", False)

    issues = unsupported_claims(turn("All tests passed!", run), [])

    assert issues == [
        "you said 'tests pass', but the last run failed: `pytest -q`"
    ]


def test_claim_backed_by_passing_run() -> None:
    runs = (
        CommandRun("pytest", "1 failed", False),
        CommandRun("pytest", "5 passed", False),
    )

    assert unsupported_claims(turn("tests are passing now", *runs), []) == []


def test_claim_backed_by_tether_checks() -> None:
    results = [CheckResult("tests", Status.PASSED)]

    assert unsupported_claims(turn("tests pass"), results) == []


def test_korean_and_other_claims() -> None:
    lint_run = CommandRun("ruff check .", "Found 2 errors.", True)

    issues = unsupported_claims(
        turn("테스트 모두 통과했고 lint is clean, pyright passes", lint_run), []
    )

    assert issues == [
        "you said 'tests pass', but nothing checked that this turn",
        "you said 'lint passes', but the last run failed: `ruff check .`",
        "you said 'type check passes', but nothing checked that this turn",
    ]


def test_no_claim_no_issue() -> None:
    assert unsupported_claims(turn("I changed the parser."), []) == []
