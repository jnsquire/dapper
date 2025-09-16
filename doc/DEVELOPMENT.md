# Development Setup

This project uses [uv](https://github.com/astral-sh/uv) for fast Python package management and project handling.

## Prerequisites

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) package manager

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd dapper
   ```

2. **Install uv (if not already installed):**
   ```bash
   # On macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # On Windows
   powershell -c "irm https://astral.sh/uv/install.sh | iex"

   # Or using pip
   pip install uv
   ```

3. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

   This will create a virtual environment and install all dependencies from `pyproject.toml`.

## Development Workflow

### Activate the virtual environment
```bash
# uv automatically manages the virtual environment
uv run python --version
```

### Running Tests

**Using uv (recommended):**
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_debugger_launch.py

# Run with coverage
uv run pytest --cov=dapper --cov-report=html
```

**Using traditional Python (if uv is not available):**
```bash
# Install dependencies manually
pip install -e .
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest
```

### Building the Package

```bash
# Build distribution packages
uv build

# Or using setuptools
python -m build
```

## Project Structure

```
dapper/
├── dapper/          # Main package
│   ├── __init__.py
│   ├── debugger.py     # Core debugger implementation
│   ├── server.py       # DAP server
│   ├── protocol.py     # DAP protocol handling
│   └── ...
├── tests/              # Test suite
│   ├── test_debugger_*.py  # Split test files
│   └── ...
├── pyproject.toml      # Project configuration
├── uv.lock            # uv lock file
└── README.md
```

## Testing Strategy

The test suite is organized into functional areas:

- `test_debugger_core.py` - Core debugger functionality
- `test_debugger_launch.py` - Launch and process management
- `test_debugger_execution.py` - Execution control (continue, step, etc.)
- `test_debugger_breakpoints.py` - Breakpoint management
- `test_debugger_variables.py` - Variable inspection
- `test_debugger_events.py` - Event handling
- `test_debugger_threads.py` - Thread management

All tests use `pytest` with async support and comprehensive mocking.

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Ensure all tests pass: `uv run pytest`
5. Submit a pull request

## Troubleshooting

### uv not found
If `uv` is not available, you can still work with the project using traditional Python tools:

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # On Windows
# source .venv/bin/activate  # On macOS/Linux

# Install dependencies
pip install -e .
pip install pytest pytest-asyncio pytest-cov
```

### Permission issues on Windows
If you encounter permission issues with uv on Windows, try running your terminal as Administrator or use:

```bash
uv run --python-preference system pytest
```
