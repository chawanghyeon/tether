from tether.config import Config
from tether.outcome import Outcome
from tether.slots import (
    Slot,
    SlotError,
    assign_slot,
    doctor,
    existing_slot,
    release_slot,
    run_slot_command,
    write_env,
)

SLOT_ACTIONS = ("show", "env", "setup", "teardown", "release", "doctor")


def slot_command(config: Config, action: str, force: bool) -> Outcome:
    try:
        return _run(config, action, force)
    except SlotError as error:
        return Outcome(1, stderr=f"tether slot: {error}")


def describe(slot: Slot) -> str:
    kind = "main worktree" if slot.worktree.is_main else "worktree"
    lines = [f"slot {slot.number} ({kind} {slot.worktree.path})"]
    lines.extend(f"{key}={value}" for key, value in slot.values.items())
    return "\n".join(lines)


def _run(config: Config, action: str, force: bool) -> Outcome:
    if action == "doctor":
        problems = doctor(config)
        if problems:
            return Outcome(1, stdout="\n".join(problems))
        return Outcome(stdout="tether slot: no conflicts")
    if action == "release":
        number = release_slot(config)
        if number is None:
            return Outcome(stdout="tether slot: nothing to release")
        return Outcome(stdout=f"tether slot: released slot {number}")
    if action == "teardown":
        return _teardown(config)
    if action == "show":
        slot = existing_slot(config)
        if slot is None:
            return Outcome(1, stderr="tether slot: no slot; run setup first")
        return Outcome(stdout=describe(slot))
    slot = assign_slot(config)
    written = write_env(config, slot, force)
    lines = [describe(slot)]
    lines.append(
        f"wrote {written}" if written else "main worktree keeps its own env"
    )
    if action == "setup":
        result = run_slot_command(config, slot, config.slot_setup)
        if result is not None and result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            return Outcome(1, "\n".join(lines), f"setup failed:\n{output}")
    return Outcome(stdout="\n".join(lines))


def _teardown(config: Config) -> Outcome:
    slot = existing_slot(config)
    if slot is None:
        return Outcome(stdout="tether slot: nothing to tear down")
    if slot.worktree.is_main:
        return Outcome(1, stderr="tether slot: refusing to tear down main")
    result = run_slot_command(config, slot, config.slot_teardown)
    if result is not None and result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        return Outcome(1, stderr=f"teardown failed; slot kept:\n{output}")
    release_slot(config)
    return Outcome(stdout=f"tether slot: tore down slot {slot.number}")
