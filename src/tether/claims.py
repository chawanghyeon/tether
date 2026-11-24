import dataclasses
import json
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from tether.checks import CheckResult, Status

SHELL_TOOLS = frozenset({"Bash"})
FAILURE_OUTPUT = re.compile(
    r"\b[1-9]\d* (?:failed|errors?)\b|\bFAILED\b|^Traceback ", re.MULTILINE
)


@dataclasses.dataclass(frozen=True)
class CommandRun:
    command: str
    output: str
    is_error: bool

    @property
    def failed(self) -> bool:
        return self.is_error or bool(FAILURE_OUTPUT.search(self.output))


@dataclasses.dataclass(frozen=True)
class TurnTranscript:
    final_text: str
    runs: tuple[CommandRun, ...]


@dataclasses.dataclass(frozen=True)
class ClaimRule:
    name: str
    check_name: str
    claim: re.Pattern[str]
    command: re.Pattern[str]


CLAIM_RULES = (
    ClaimRule(
        "tests pass",
        "tests",
        re.compile(
            r"\b(?:all\s+)?(?:tests?|specs?|pytest)\s+(?:are\s+|now\s+)?"
            r"(?:all\s+)?(?:pass(?:es|ed|ing)?|green|succeed(?:ed|s)?)\b"
            r"|테스트[가는를]?\s*(?:모두\s*|전부\s*)?(?:통과|성공)",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:pytest|tox|nox|make\s+test|npm\s+test)\b"),
    ),
    ClaimRule(
        "lint passes",
        "lint",
        re.compile(
            r"\b(?:lint(?:ing|er)?|ruff)\s+(?:is\s+|now\s+)?"
            r"(?:pass(?:es|ed)?|clean)\b|린트\s*(?:모두\s*)?통과",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:ruff|flake8|pylint)\b"),
    ),
    ClaimRule(
        "type check passes",
        "typecheck",
        re.compile(
            r"\b(?:type\s*-?check(?:s|ing)?|pyright|mypy)\s+(?:is\s+|now\s+)?"
            r"(?:pass(?:es|ed)?|clean)\b|타입\s*체크\s*(?:모두\s*)?통과",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:pyright|mypy)\b"),
    ),
)


def read_turn(transcript: Path, since: float = 0.0) -> TurnTranscript:
    entries = list(_entries(transcript))
    start = _turn_start(entries, since)
    final_text = ""
    pending: dict[str, str] = {}
    runs: list[CommandRun] = []
    for entry in entries[start:]:
        role = entry.get("type")
        for block in _blocks(entry):
            kind = block.get("type")
            if role == "assistant" and kind == "text":
                final_text = str(block.get("text", ""))
            elif role == "assistant" and kind == "tool_use":
                if block.get("name") in SHELL_TOOLS:
                    command = (block.get("input") or {}).get("command", "")
                    pending[str(block.get("id"))] = str(command)
            elif role == "user" and kind == "tool_result":
                command = pending.pop(str(block.get("tool_use_id")), None)
                if command is not None:
                    runs.append(
                        CommandRun(
                            command,
                            _result_text(block.get("content")),
                            bool(block.get("is_error", False)),
                        )
                    )
    return TurnTranscript(final_text, tuple(runs))


def unsupported_claims(
    turn: TurnTranscript, results: Sequence[CheckResult]
) -> list[str]:
    passed_checks = {r.name for r in results if r.status is Status.PASSED}
    issues = []
    for rule in CLAIM_RULES:
        if not rule.claim.search(turn.final_text):
            continue
        if rule.check_name in passed_checks:
            continue
        runs = [run for run in turn.runs if rule.command.search(run.command)]
        if not runs:
            issues.append(
                f"you said {rule.name!r}, but nothing checked that this turn"
            )
        elif runs[-1].failed:
            issues.append(
                f"you said {rule.name!r}, but the last run failed: "
                f"`{runs[-1].command}`"
            )
    return issues


def _entries(transcript: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = transcript.read_text().splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("message"), dict):
            yield entry


def _turn_start(entries: Sequence[dict[str, Any]], since: float) -> int:
    if since > 0:
        for index, entry in enumerate(entries):
            stamp = _timestamp(entry)
            if stamp is not None and stamp >= since:
                return index
    for index in range(len(entries) - 1, -1, -1):
        if _is_prompt(entries[index]):
            return index + 1
    return 0


def _timestamp(entry: dict[str, Any]) -> float | None:
    value = entry.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _is_prompt(entry: dict[str, Any]) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = entry["message"].get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _blocks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    content = entry["message"].get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str) and entry.get("type") == "assistant":
        return [{"type": "text", "text": content}]
    return []


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
