# tether

Fast, turn-aware checks and reloads for coding agents.

Coding agents edit many files quickly. Tools built for human speed get in
the way: the full test suite runs on every change, and auto-reload restarts
the dev server on every save. `tether` ties checks and reloads to the
agent's turn instead.

| When | What runs | Target time |
|---|---|---|
| After each edit (`on-edit`) | Lint on the edited file only | < 1s |
| At the end of a turn (`on-stop`) | Lint and typecheck on the turn's files, then only the related tests | seconds |
| By hand (`tether check --full`) | Everything | any |

If the end-of-turn checks fail, the agent is blocked from stopping and gets
a short report to fix, up to `max_stop_attempts` times. Then `tether`
restarts a running `tether serve` once, and only if a source file changed.

## Install

```bash
uv tool install --editable .
```

## Use with Claude Code

Print the hook settings and merge them into your project's
`.claude/settings.json`:

```bash
tether hooks
```

Run your dev server without its own reloader:

```bash
tether serve -- uvicorn app:app
```

## How the turn works

1. `on-prompt` (UserPromptSubmit) starts a turn and records the time.
2. `on-edit` (PostToolUse) records the edited file and lints it.
3. `on-stop` (Stop) finds the turn's files: recorded edits, plus git
   changes modified since the turn started (this catches edits made from the
   shell). It runs the checks within `stop_timeout_seconds`.

Related tests are picked by `pytest-testmon` when it is installed in the
project's `.venv`, or else by name: `src/pkg/orders.py` selects
`tests/**/test_orders.py` and `tests/**/orders_test.py`. A changed
`conftest.py` selects the tests next to it.

Commands are looked up in the project's `.venv/bin` first, then on `PATH`.
Missing tools are skipped, not failed.

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
```

## Demo

`examples/demo-app` is a small stdlib server with hooks already set up.
Open a Claude Code session in that folder and ask it to change the VAT rate.

```bash
cd examples/demo-app
PYTHONPATH=src tether serve -- python3 -m demo_app.server
```

## Development

```bash
uv run pytest
uv run ruff check
uv run pyright
```
