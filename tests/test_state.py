from pathlib import Path

from tether.state import (
    TurnState,
    load_turn,
    locked_turn,
    record_edit,
    reset_turn,
    state_dir,
)


def test_missing_state_is_empty(tmp_path: Path) -> None:
    assert load_turn(tmp_path) == TurnState()


def test_record_edit_deduplicates(tmp_path: Path) -> None:
    record_edit(tmp_path, "src/a.py")
    record_edit(tmp_path, "src/a.py")
    record_edit(tmp_path, "src/b.py")

    assert load_turn(tmp_path).edited == ["src/a.py", "src/b.py"]


def test_reset_turn_clears_edits_and_attempts(tmp_path: Path) -> None:
    record_edit(tmp_path, "src/a.py")
    with locked_turn(tmp_path) as state:
        state.attempts = 2

    reset_turn(tmp_path, now=123.0)

    assert load_turn(tmp_path) == TurnState(started_at=123.0)


def test_corrupt_state_is_treated_as_empty(tmp_path: Path) -> None:
    (state_dir(tmp_path) / "turn.json").write_text("{not json")

    assert load_turn(tmp_path) == TurnState()


def test_state_dir_ignores_itself_in_git(tmp_path: Path) -> None:
    assert (state_dir(tmp_path) / ".gitignore").read_text() == "*\n"
