import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from tether.changes import changed_since
from tether.checks import (
    Deadline,
    Status,
    failed,
    format_report,
    run_check,
    run_full_checks,
    run_turn_checks,
    summarize,
)
from tether.config import Config, ConfigError, find_root, load_config
from tether.hooks import (
    BLOCK_EXIT_CODE,
    HookInput,
    parse_hook_input,
    relative_to_root,
    system_message,
)
from tether.outcome import Outcome
from tether.slot_cli import SLOT_ACTIONS, slot_command
from tether.state import load_turn, locked_turn, record_edit, reset_turn
from tether.supervisor import Supervisor, request_reload, should_reload

EDIT_LINT_TIMEOUT_SECONDS = 10.0
PYTHON_SUFFIX = ".py"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"
STOP_HOOK_TIMEOUT_SECONDS = 180
EDIT_TOOLS_MATCHER = "Edit|MultiEdit|Write|NotebookEdit"


def on_prompt(config: Config, now: float) -> Outcome:
    reset_turn(config.root, now)
    return Outcome()


def on_edit(config: Config, hook: HookInput) -> Outcome:
    if hook.file_path is None:
        return Outcome()
    relative = relative_to_root(hook.file_path, config.root)
    if relative is None:
        return Outcome()
    record_edit(config.root, relative)
    if not (
        config.lint_on_edit
        and relative.endswith(PYTHON_SUFFIX)
        and (config.root / relative).is_file()
    ):
        return Outcome()
    result = run_check(
        "lint",
        (*config.lint_command, relative),
        config.root,
        EDIT_LINT_TIMEOUT_SECONDS,
    )
    if result.status is not Status.FAILED:
        return Outcome()
    report = format_report([result], config.max_report_chars)
    return Outcome(BLOCK_EXIT_CODE, stderr=report)


def on_stop(config: Config, now: float) -> Outcome:
    turn = load_turn(config.root)
    changed = changed_since(config.root, turn.started_at, turn.edited)
    results = run_turn_checks(
        config, changed, Deadline.after(config.stop_timeout_seconds)
    )
    failures = failed(results)
    if failures and turn.attempts < config.max_stop_attempts:
        with locked_turn(config.root) as state:
            state.attempts += 1
        report = format_report(results, config.max_report_chars)
        return Outcome(BLOCK_EXIT_CODE, stderr=report)
    messages = []
    if failures:
        messages.append(
            f"tether: still failing after {turn.attempts} fix attempts. "
            + summarize(results)
        )
    if any(result.status is Status.TIMED_OUT for result in results):
        messages.append("tether: checks timed out; run `tether check`")
    if should_reload(changed, config.reload_globs) and request_reload(
        config.root
    ):
        messages.append("tether: server reloaded")
    reset_turn(config.root, now)
    stdout = system_message("\n".join(messages)) if messages else ""
    return Outcome(stdout=stdout)


def check(config: Config, full: bool) -> Outcome:
    if full:
        results = run_full_checks(config)
    else:
        turn = load_turn(config.root)
        changed = changed_since(config.root, turn.started_at, turn.edited)
        results = run_turn_checks(config, changed, Deadline.after(None))
    report = format_report(results, config.max_report_chars)
    return Outcome(1 if failed(results) else 0, stdout=report)


def reload(config: Config) -> Outcome:
    if request_reload(config.root):
        return Outcome(stdout="tether: reload requested")
    return Outcome(1, stderr="tether: no `tether serve` running")


def hooks_settings() -> str:
    def command(name: str, **extra: object) -> dict[str, object]:
        return {"type": "command", "command": f"tether {name}", **extra}

    settings = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [command("on-prompt")]}],
            "PostToolUse": [
                {
                    "matcher": EDIT_TOOLS_MATCHER,
                    "hooks": [command("on-edit")],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        command("on-stop", timeout=STOP_HOOK_TIMEOUT_SECONDS)
                    ]
                }
            ],
        }
    }
    return json.dumps(settings, indent=2)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        outcome = _dispatch(args)
    except ConfigError as error:
        outcome = Outcome(1, stderr=f"tether: {error}")
    if outcome.stdout:
        print(outcome.stdout)
    if outcome.stderr:
        print(outcome.stderr, file=sys.stderr)
    sys.exit(outcome.exit_code)


def _dispatch(args: argparse.Namespace) -> Outcome:
    if args.command == "hooks":
        return Outcome(stdout=hooks_settings())
    if args.command in ("on-prompt", "on-edit", "on-stop"):
        hook = parse_hook_input(sys.stdin, Path.cwd())
        config = load_config(find_root(_project_dir(hook.cwd)))
        if args.command == "on-prompt":
            return on_prompt(config, time.time())
        if args.command == "on-edit":
            return on_edit(config, hook)
        return on_stop(config, time.time())
    config = load_config(find_root(_project_dir(Path.cwd())))
    if args.command == "check":
        return check(config, args.full)
    if args.command == "reload":
        return reload(config)
    if args.command == "slot":
        return slot_command(config, args.action, args.force)
    server_command = _strip_separator(args.server_command)
    if not server_command:
        return Outcome(2, stderr="tether serve: missing command after --")
    return Outcome(Supervisor(server_command, config.root).run())


def _strip_separator(command: list[str]) -> list[str]:
    return command[1:] if command[:1] == ["--"] else command


def _project_dir(fallback: Path) -> Path:
    return Path(os.environ.get(PROJECT_DIR_ENV) or fallback)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tether")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("on-prompt", help="hook: start a turn")
    commands.add_parser("on-edit", help="hook: record and lint an edit")
    commands.add_parser("on-stop", help="hook: check the turn, then reload")
    check_parser = commands.add_parser("check", help="run checks now")
    check_parser.add_argument(
        "--full", action="store_true", help="run the whole suite"
    )
    serve_parser = commands.add_parser("serve", help="run a dev server")
    serve_parser.add_argument("server_command", nargs=argparse.REMAINDER)
    commands.add_parser("reload", help="restart the served dev server")
    commands.add_parser("hooks", help="print Claude Code hook settings")
    slot_parser = commands.add_parser(
        "slot", help="give this worktree its own ports, env, and databases"
    )
    slot_parser.add_argument(
        "action", choices=SLOT_ACTIONS, nargs="?", default="show"
    )
    slot_parser.add_argument(
        "--force", action="store_true", help="overwrite a hand-written env file"
    )
    return parser
