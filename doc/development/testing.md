# Testing

This page covers the test organisation and how to run the test suite. For environment setup, see [Setup](setup.md).

## Test Organisation

The test suite is organised into functional areas. Each file focuses on one aspect of the debugger:

| File | Scope |
|------|-------|
| `test_debugger_core.py` | Core debugger functionality |
| `test_debugger_launch.py` | Launch and process management |
| `test_debugger_execution.py` | Execution control (continue, step, etc.) |
| `test_debugger_breakpoints.py` | Breakpoint management |
| `test_debugger_variables.py` | Variable inspection |
| `test_debugger_events.py` | Event handling |
| `test_debugger_threads.py` | Thread management |

All tests use `pytest` with async support and comprehensive mocking.

The broader test suite also includes:

- `tests/unit/` — isolated unit tests for individual modules
- `tests/integration/` — integration tests that exercise multiple components together
- `tests/functional/` — end-to-end functional tests
- `tests/core/` — tests for core components

## Running Tests

**Using uv (recommended):**
```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_debugger_core.py

# Run a specific test by name
uv run pytest -k "test_launch"

# Run with verbose output
uv run pytest -v

# Run with coverage
uv run pytest --cov=dapper

# Run a specific subdirectory
uv run pytest tests/unit/
```

Before submitting changes, always run the full suite:

```bash
uv run pytest
uv run ruff check .
```

## See Also

- [Setup](setup.md)
- [Contributing](contributing.md)
