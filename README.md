# tether

Keep coding agents fast, honest, and inside your architecture.

Coding agents edit many files quickly, often in parallel. Tools built for
human speed get in the way, and the agent's own reports are not always true.
`tether` is a CLI plus Claude Code hooks that:

- **checks at the right time**: lint on each edit, related tests at the end
  of a turn, the full suite only when you ask;
- **reloads once per turn**: your dev server restarts when the agent is
  done, not on every save;
- **isolates worktrees**: each git worktree gets its own ports, env file,
  and databases;
- **enforces structure**: new files, forbidden patterns, and import
  boundaries are checked as code, not as a request in `CLAUDE.md`;
- **catches false claims and test tampering**: "tests pass" with no test
  run, deleted assertions, new `skip` markers, swallowed exceptions;
- **summarizes structure**: what changed by module and symbol, so you keep a
  map of the code without reading every line.

## Install

```bash
uv tool install --editable .
```

Commands such as `ruff`, `pyright`, and `pytest` are looked up in the
project's `.venv/bin` first, then on `PATH`. Missing tools are skipped, not
failed.

## Use with Claude Code

Print the hook settings and merge them into your project's
`.claude/settings.json`:

```bash
tether hooks
```

| Hook | Command | What it does |
|---|---|---|
| UserPromptSubmit | `tether on-prompt` | Starts a turn and snapshots the working tree |
| PostToolUse (edits) | `tether on-edit` | Records the file; runs guard rules and lint on it |
| Stop | `tether on-stop` | Runs turn checks, claim and tamper checks, writes the summary, reloads the server |

When `on-edit` or `on-stop` finds a problem, it exits with code 2 and the
agent gets a short report to fix. `on-stop` gives up after
`max_stop_attempts` and tells you instead.

## Checks per turn

At the end of a turn, `tether` finds the turn's files (recorded edits, plus
git changes made since the turn started, which catches shell edits) and runs:

1. guard rules on those files,
2. lint and type check on those files,
3. only the related tests: by `pytest-testmon` when it is installed in the
   project's `.venv`, or by name (`src/pkg/orders.py` selects
   `tests/**/test_orders.py` and `tests/**/orders_test.py`; a changed
   `conftest.py` selects the tests next to it).

Everything runs within `stop_timeout_seconds`. Run the whole suite by hand:

```bash
tether check --full
```

## Reload once per turn

Run your dev server without its own reloader:

```bash
tether serve -- uvicorn app:app
```

At the end of a turn that changed a file matching `reload_globs`, the
server restarts once. `tether reload` restarts it by hand.

## Worktree slots

Each git worktree gets a stable slot number (the main worktree is 0).
Templates in `[tool.tether.slot_env]` are rendered per slot with `{slot}`,
`{8000 + slot}`, and `{name}` (the worktree folder name).

```toml
[tool.tether.slot_env]
PORT = "{8000 + slot}"
DATABASE_URL = "postgresql://localhost/app_wt_{slot}"
COMPOSE_PROJECT_NAME = "app_{name}"

[tool.tether]
slot_setup = ["createdb", "-T", "app_template", "app_wt_{slot}"]
slot_teardown = ["dropdb", "--if-exists", "app_wt_{slot}"]
```

```bash
git worktree add ../app-feature -b feature
cd ../app-feature
tether slot setup     # assign a slot, write .env, run slot_setup
tether slot doctor    # report shared ports, URLs, or missing env files
tether slot teardown  # run slot_teardown and free the slot
```

`setup` copies the main worktree's env file and overrides the slot values.
It never touches the main worktree's file, and it refuses to overwrite a
file it did not write unless you pass `--force`.

## Guard rules

Only new files and added lines are checked, so existing code never blocks
the agent.

```toml
[tool.tether]
layout = ["src/app/**/*.py", "tests/**/*.py"]

[[tool.tether.forbid]]
pattern = "\\bprint\\("
message = "use logging"
paths = ["src/**/*.py"]

[[tool.tether.imports]]
source = "src/app/domain/**/*.py"
forbid = ["app.api", "app.infra", "fastapi"]
message = "domain must not depend on outer layers"
```

- `layout`: new Python files must match one of these globs.
- `forbid`: a regex that must not appear on added lines in `paths`.
- `imports`: files matching `source` must not import these modules,
  including through relative imports.

## Claims and tampering

At the end of a turn, `tether` reads the agent's last message from the
transcript. If it says tests, lint, or type checks pass (in English or
Korean) and nothing backs it up (no matching command ran, or the last run
failed, and tether's own check did not pass), the agent is asked to run the
check or correct the message.

It also diffs the turn against the snapshot taken at its start, and reports:

- removed assertions, deleted test functions, deleted test files,
- new `skip`/`xfail` markers,
- new `# type: ignore`, `# noqa`, `# pyright: ignore`,
- new `except ...: pass` blocks.

These are shown to you. Set `tamper_blocks = true` to send them back to the
agent instead.

## Summary

After each turn you get one line, such as
`tether: 3 file(s) (+40 -5), 2 symbol(s) added, new imports: requests`, and
the full report in `.tether/summary.md`: changed files by folder, added and
removed functions and classes, signature changes, and new third-party
imports.

```bash
tether summary              # this turn
tether summary --since main # everything since a ref
```

## Configuration

All keys are optional. Defaults shown:

```toml
[tool.tether]
source_dirs = ["src"]
test_dirs = ["tests"]
lint_command = ["ruff", "check", "--quiet"]
typecheck_command = ["pyright"]
test_command = ["pytest", "-q"]
selection = "auto"            # "auto", "testmon", or "path"
lint_on_edit = true
max_stop_attempts = 2
stop_timeout_seconds = 60
reload_globs = ["src/**/*.py"]
max_report_chars = 4000
slot_env_file = ".env"
slot_setup = []
slot_teardown = []
max_slots = 50
layout = []
verify_claims = true
tamper_blocks = false
summary_on_stop = true
```

## Demo

`examples/demo-app` is a small stdlib server with hooks, guard rules, and a
slot port already set up. Open a Claude Code session in that folder and ask
it to change the VAT rate.

```bash
cd examples/demo-app
PYTHONPATH=src tether serve -- python3 -m demo_app.server
```

## Development

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```
