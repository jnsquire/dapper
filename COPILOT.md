# Dapper AI - GitHub Copilot Instructions

## Project Overview
Debug Adapter Protocol (DAP) implementation for Python debugging. Core components:
- `dapper/debugger.py` - Main debugger with subprocess integration
- `dapper/server.py` - DAP server handling protocol messages
- `dapper/protocol.py` - DAP message parsing and serialization
- Tests split by functionality: core, launch, execution, breakpoints, variables, events, threads

## Preferred Tools
- **uv** - Fast Python package manager (preferred over pip)
- **pytest** - Testing framework with async support
- **Path.resolve()** - Always use for path handling

## Development Setup
```bash
# Install dependencies
uv sync

# Activate environment
uv run python --version

# Dapper — Copilot guidance (concise)

Project: Python DAP implementation (core modules under `dapper/`).

Quick commands
```powershell
# install deps
uv sync
# run tests
uv run pytest
# run a single test
uv run pytest tests/test_debugger_launch.py -q
```

Testing guidance
- Use small, focused unit tests and existing base test helpers.
- Mock subprocess and IO; use `IsolatedAsyncioTestCase` for async code.

Type & API notes
- Use type hints wherever the intended type is clear.
- Use TypedDicts in preference to dict types.
- Prefer debugger-provided `make_variable_object` when available; `debug_shared.make_variable_object` is the safe fallback.

Temporary scripts
- Put short repros and one-off scripts in `tools/temp_scripts/`.
- Do not commit secrets; move useful scripts into `tools/` and add tests.

File layout (high level)
```
dapper/        # package source
tests/         # pytest test suite
tools/temp_scripts/  # local repros and short utilities
```

Keep changes small and covered by tests.

