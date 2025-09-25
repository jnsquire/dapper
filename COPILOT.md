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

# Run tests
uv run pytest

# Run specific tests
uv run pytest tests/test_debugger_launch.py -v
```

## Testing Guidelines
- Use `BaseDebuggerTest` for common setup/teardown
- Mock subprocess.Popen with `wait.return_value = 0`
- Mock stdout/stderr with `readline.return_value = ""`
- Test async methods with `IsolatedAsyncioTestCase`
- Focus on functional areas, not monolithic files

## Code Patterns
```python
# Path handling
program_path = str(Path(program).resolve())

# Async subprocess execution
await self.loop.run_in_executor(
    self.executor, self._start_debuggee_process, debug_args
)

# Mock setup for tests
mock_process = MagicMock()
mock_process.wait.return_value = 0
mock_process.stdout.readline.return_value = ""
```

## Type Safety Guidelines
- **Always use type hints** - Prefer explicit typing for better code clarity and IDE support
- **TypedDict constructors** - Use TypedDict classes instead of bare dict literals for DAP messages
- **Proper imports** - Import types from `typing` and `protocol_types`

```python
# Good: Use type hints and TypedDict constructors
from dapper.protocol_types import LoadedSourcesResponse, Source

def get_sources() -> list[Source]:
    sources: list[Source] = []
    source = Source(
        name="example.py",
        path="/path/to/example.py",
        origin="main"
    )
    sources.append(source)
    return sources

# Avoid: Bare dict literals and missing type hints
def get_sources():
    sources = []
    source = {"name": "example.py", "path": "/path/to/example.py"}
    sources.append(source)
    return sources
```

## Common Issues
- **Hanging tests**: Ensure mock process has `wait.return_value = 0`
- **Path resolution**: Use `Path.resolve()` for consistent paths
- **Threading**: Use `asyncio.run_coroutine_threadsafe()` for thread communication

## Key Commands
```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=dapper

# Format code (if configured)
uv run black dapper tests

# Lint code (if configured)
uv run flake8 dapper tests
```

A short note for contributors: this project currently treats internal APIs as
free to change without backward-compatibility guarantees. When you change
internal function/method signatures or move helpers between modules, prefer
clear commit messages and update tests rather than adding compatibility
shims. The minimal test above is a lightweight, executable reminder of that
stance.

## Architecture Notes
- **Event-driven**: Uses asyncio for non-blocking operations
- **Thread-safe**: Separate threads for subprocess I/O
- **Protocol-based**: Strict DAP message format compliance
- **Modular**: Split functionality across focused modules

## Testing Strategy
- Unit tests with comprehensive mocking
- Functional area separation (7 test files)
- Async test support with `pytest-asyncio`
- Coverage reporting with `pytest-cov`

## File Organization
```
dapper/
├── debugger.py      # Core debugging logic
├── server.py        # DAP server
├── protocol.py      # Message handling
└── debug_launcher.py # Subprocess launcher

tests/
├── test_debugger_*.py  # Functional test files
└── test_debugger_base.py # Shared test setup
```</content>
<parameter name="filePath">c:\Users\joel\dapper\COPILOT.md
