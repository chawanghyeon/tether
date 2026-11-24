import dataclasses
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import add_worktree, git
from tether.config import Config
from tether.slots import (
    GENERATED_HEADER,
    SlotError,
    assign_slot,
    doctor,
    existing_slot,
    merge_env,
    parse_env,
    release_slot,
    render,
    run_slot_command,
    write_env,
)

SLOT_ENV = {
    "PORT": "{8000 + slot}",
    "DATABASE_URL": "postgresql://localhost/app_wt_{slot}",
    "COMPOSE_PROJECT_NAME": "app_{name}",
}


def config_for(root: Path, **overrides: Any) -> Config:
    base = Config(root=root, slot_env=dict(SLOT_ENV))
    return dataclasses.replace(base, **overrides)


def test_render_supports_offsets_and_names() -> None:
    assert render("{8000 + slot}", 3, "wt") == "8003"
    assert render("db_{slot}_{name}", 2, "feature") == "db_2_feature"
    assert render("{ slot }", 4, "x") == "4"
    assert render("{other}", 1, "x") == "{other}"


def test_main_worktree_is_slot_zero(main_repo: Path) -> None:
    slot = assign_slot(config_for(main_repo))

    assert slot.number == 0
    assert slot.values["PORT"] == "8000"


def test_worktrees_get_distinct_stable_slots(main_repo: Path) -> None:
    first = add_worktree(main_repo, "wt-a")
    second = add_worktree(main_repo, "wt-b")

    a = assign_slot(config_for(first))
    b = assign_slot(config_for(second))

    assert {a.number, b.number} == {1, 2}
    assert assign_slot(config_for(first)).number == a.number
    assert a.values["COMPOSE_PROJECT_NAME"] == "app_wt-a"


def test_release_frees_slot_for_reuse(main_repo: Path) -> None:
    first = add_worktree(main_repo, "wt-a")
    second = add_worktree(main_repo, "wt-b")
    assert assign_slot(config_for(first)).number == 1

    assert release_slot(config_for(first)) == 1

    assert assign_slot(config_for(second)).number == 1


def test_removed_worktree_slot_is_pruned(main_repo: Path) -> None:
    first = add_worktree(main_repo, "wt-a")
    assign_slot(config_for(first))
    git(main_repo, "worktree", "remove", str(first))
    second = add_worktree(main_repo, "wt-b")

    assert assign_slot(config_for(second)).number == 1


def test_slots_run_out(main_repo: Path) -> None:
    first = add_worktree(main_repo, "wt-a")
    second = add_worktree(main_repo, "wt-b")
    assign_slot(config_for(first, max_slots=2))

    with pytest.raises(SlotError, match="slots are in use"):
        assign_slot(config_for(second, max_slots=2))


def test_parse_env_skips_comments() -> None:
    text = "# note\nexport A=1\nB = two\n\nnot a line\n"

    assert parse_env(text) == {"A": "1", "B": "two"}


def test_merge_env_overrides_and_appends() -> None:
    merged = merge_env("A=1\nPORT=8000\n# keep\n", {"PORT": "8001", "Z": "z"})

    assert merged == f"{GENERATED_HEADER}\nA=1\nPORT=8001\n# keep\nZ=z\n"


def test_write_env_copies_main_env_with_slot_values(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    config = config_for(worktree)

    target = write_env(config, assign_slot(config))

    assert target is not None
    assert target == worktree / ".env"
    values = parse_env(target.read_text())
    assert values["SECRET"] == "abc"
    assert values["PORT"] == "8001"
    assert values["DATABASE_URL"] == "postgresql://localhost/app_wt_1"


def test_write_env_never_touches_main(main_repo: Path) -> None:
    config = config_for(main_repo)
    before = (main_repo / ".env").read_text()

    assert write_env(config, assign_slot(config)) is None
    assert (main_repo / ".env").read_text() == before


def test_write_env_refuses_hand_written_file(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    (worktree / ".env").write_text("MINE=1\n")
    config = config_for(worktree)
    slot = assign_slot(config)

    with pytest.raises(SlotError, match="--force"):
        write_env(config, slot)

    write_env(config, slot, force=True)
    assert parse_env((worktree / ".env").read_text())["PORT"] == "8001"


def test_run_slot_command_renders_args_and_env(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    config = config_for(worktree)
    script = "import os, sys; print(sys.argv[1], os.environ['PORT'])"

    result = run_slot_command(
        config, assign_slot(config), ["python", "-c", script, "db_{slot}"]
    )

    assert result is not None
    assert result.stdout.strip() == "db_1 8001"


def test_doctor_reports_missing_and_shared_values(main_repo: Path) -> None:
    worktree = add_worktree(main_repo, "wt-a")
    other = add_worktree(main_repo, "wt-b")
    config = config_for(worktree)
    write_env(config, assign_slot(config))
    (other / ".env").write_text("PORT=8001\n")

    problems = doctor(config)

    assert any("wt-b: no slot" in problem for problem in problems)
    assert any("PORT=8001 is shared" in problem for problem in problems)


def test_doctor_is_clean_after_setup(main_repo: Path) -> None:
    for name in ("wt-a", "wt-b"):
        config = config_for(add_worktree(main_repo, name))
        write_env(config, assign_slot(config))

    assert doctor(config_for(main_repo)) == []


def test_outside_git_raises(tmp_path: Path) -> None:
    with pytest.raises(SlotError):
        assign_slot(config_for(tmp_path))


def test_existing_slot_does_not_allocate(main_repo: Path) -> None:
    config = config_for(add_worktree(main_repo, "wt-a"))

    assert existing_slot(config) is None
    number = assign_slot(config).number
    slot = existing_slot(config)
    assert slot is not None
    assert slot.number == number
