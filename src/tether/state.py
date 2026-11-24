import dataclasses
import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

STATE_DIR = ".tether"
TURN_FILE = "turn.json"
LOCK_FILE = "turn.lock"


@dataclasses.dataclass
class TurnState:
    started_at: float = 0.0
    edited: list[str] = dataclasses.field(default_factory=list)
    attempts: int = 0
    baseline: str = ""


def state_dir(root: Path) -> Path:
    path = root / STATE_DIR
    path.mkdir(exist_ok=True)
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return path


@contextmanager
def locked_turn(root: Path) -> Iterator[TurnState]:
    directory = state_dir(root)
    with open(directory / LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read(directory / TURN_FILE)
        yield state
        _write(directory / TURN_FILE, state)


def load_turn(root: Path) -> TurnState:
    return _read(state_dir(root) / TURN_FILE)


def reset_turn(root: Path, now: float, baseline: str = "") -> None:
    with locked_turn(root) as state:
        state.started_at = now
        state.edited.clear()
        state.attempts = 0
        state.baseline = baseline


def record_edit(root: Path, relative_path: str) -> None:
    with locked_turn(root) as state:
        if relative_path not in state.edited:
            state.edited.append(relative_path)


def _read(path: Path) -> TurnState:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return TurnState()
    return TurnState(
        started_at=float(raw.get("started_at", 0.0)),
        edited=[str(item) for item in raw.get("edited", [])],
        attempts=int(raw.get("attempts", 0)),
        baseline=str(raw.get("baseline", "")),
    )


def _write(path: Path, state: TurnState) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dataclasses.asdict(state)))
    os.replace(temporary, path)
