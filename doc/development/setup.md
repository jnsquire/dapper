# Development Setup

This page covers how to set up a local development environment for dapper. For contribution guidelines, see [Contributing](contributing.md).

## Prerequisites

- Python 3.9+
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

### Activate the Virtual Environment

uv automatically manages the virtual environment. You can verify the active Python:

```bash
uv run python --version
```

### Running Tests

**Using uv (recommended):**
```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_debugger_core.py

# Run with coverage
uv run pytest --cov=dapper
```

### Linting and Type Checking

Run these checks before submitting changes:

```bash
# Lint
uv run ruff check .

# Type checking
uv run pyright dapper tests
```

Optional auto-fix for lint findings:

```bash
uv run ruff check . --fix
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
├── uv.lock             # uv lock file
└── README.md
```

## Project Policies

These are current, informal policies the team follows during development.

- **API stability**: Don't worry about backward compatibility of internal interfaces when making changes — there are no outside users right now. This means it's acceptable to change function/method signatures, rename internal helpers, or move responsibilities between modules without maintaining deprecated shims. Still aim to keep changes well-documented in commit messages and update tests accordingly.

## Troubleshooting

### uv not found

If `uv` is not available, you can still work with the project using traditional Python tools:

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate   # On Windows

# Install dependencies
pip install -e .
pip install pytest pytest-asyncio pytest-cov
```

### Permission issues on Windows

If you encounter permission issues with uv on Windows, try running your terminal as Administrator or use:

```bash
uv run --python-preference system pytest
```

## See Also

- [Testing](testing.md)
- [Contributing](contributing.md)
- [VS Code Extension](vscode-extension.md)
- [Documentation](docs.md)
