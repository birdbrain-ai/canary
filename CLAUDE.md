# CLAUDE.md

## Project Overview

Canary is an agent workflow for evaluating the compiler optimization remarks for coding agents.
In this workflow, agents are tasked with 'repairing' optimization remarks by making source code changes.
The core canary library is implemented in @src/canary.

## Environment

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management.

- **Python version:** managed via `.python-version` or `pyproject.toml`
- **Install deps:** `uv sync --all-extras`
- **Run a script:** `uv run python script.py`
- **Add a dep:** `uv add <package>`
- **Add a dev dep:** `uv add --dev <package>`

## Common Commands

Use [`just`](https://just.systems/) to run dev tasks:

```
just          # list available recipes
just lint     # run linter (ruff)
just format   # format code
just fix      # auto-fix lint issues
just hint     # show unsafe fixes for lint issues
```

All `just` recipes run inside the `uv` environment automatically — no manual activation needed.

## Code Style

- Line length: 80 (ruff default)

Fix lint/format before committing: `just fix && just format`

## Project Structure

```
src/
  canary/        # main source package
tests/           # pytest tests
pyproject.toml   # project metadata and tool config
justfile         # dev task recipes
```

## Testing

```
just test                        # run all tests
uv run pytest tests/foo_test.py  # run a specific file
uv run pytest -k "test_name"     # run by name pattern
```

## Notes

- Do not commit `.venv/` or `__pycache__/`
- Keep `uv.lock` committed for reproducible installs
- Do not sign commits as Claude