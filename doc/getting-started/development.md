# Development Setup

This project uses [uv](https://github.com/astral-sh/uv) for fast Python package management and project handling.

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

## VS Code Extension Development

The VS Code extension source code is located in `vscode/extension`. This is a separate npm project that needs to be built before running the Python unit tests.

### Setup

1. **Navigate to the extension directory:**
	```bash
	cd vscode/extension
	```

2. **Install dependencies:**
	```bash
	npm install
	```

3. **Build the extension:**
	```bash
	npm run build
	```

	Or for development with auto-rebuild:
	```bash
	npm run watch
	```

### Running the Extension

1. Open the `vscode/extension` folder in VS Code.
2. Press `F5` to launch the Extension Development Host.

### Building the Package

```bash
# Build distribution packages
uv build

# Or using setuptools
python -m build
```

### Updating documentation (MkDocs + Mermaid)

We provide a small helper that renders the Mermaid `.mmd` diagrams and builds
the MkDocs site locally. Recommended (reproducible) command that ensures the
project and development dependencies are available for the run:

```bash
# Install dev dependencies for the run and make the project editable so the
# `docs` console-script entry point is available, then run the docs helper:
uv run --only-dev --with-editable . docs
```

If you only want to run the helper directly (without asking uv to install dev
dependencies for the run), you can invoke the script directly. This requires
that `mkdocs` and the Mermaid plugin are already available in the active
environment:

```bash
uv run python scripts/update_docs.py
```

Force a full re-render of Mermaid diagrams by appending the extra `--`
argument which is forwarded to the helper script:

```bash
uv run --only-dev --with-editable . docs -- --force
```

The helper will write the built site into `./site/` and will skip re-rendering
diagrams when the generated SVGs are up-to-date unless `--force` is provided.


### Asynchronous Task Scheduling Helpers

The debugger codebase avoids creating coroutine objects off the target event loop thread. Two helper APIs exist in `PyDebugger` (see `dapper/server.py`) to keep this consistent:

`spawn(factory)`
* Call only when you know you're already running on the debugger's loop (`debugger.loop`).
* `factory` is a zero-argument callable returning a coroutine object.
* Returns the created `asyncio.Task` (tracked internally) or `None` if creation fails.

`spawn_threadsafe(factory)`
* Use everywhere else (threads reading stdout/stderr, process wait threads, tests, or uncertain context).
* Schedules the factory for execution on the debugger loop without first creating the coroutine off-loop.
* Special test-friendly behavior: if the debugger loop is not yet running but another loop is active (pytest's loop), it executes immediately on that active loop so mocks observing `send_event` see results synchronously.

Guidelines:
* Prefer passing a factory (`lambda: some_coro(arg)`) instead of a pre-created coroutine object.
* Do not use `asyncio.run_coroutine_threadsafe` directly unless you require the returned `Future` for synchronization; otherwise defer to `spawn_threadsafe` to centralize task tracking and error handling.
* If you remove tasks manually, also discard them from the `_bg_tasks` set to prevent memory growth.
* IPC management is handled by `IPCManager` (`dapper/ipc/ipc_manager.py`), which delegates transport details to `ConnectionBase` implementations via `TransportFactory`.

## Git Workflow and Commit Guidelines

This project follows Git best practices to maintain a clean and meaningful commit history.

### Git Workflow Principles

1. **Make atomic commits** - Each commit should address a single concern or implement one logical change
2. **Prepare changes thoughtfully** - Review your changes before committing
3. **Write clear commit messages** - Describe what and why, not just what

### Commit Guidelines

**Good commit examples:**
```
Add TypedDict annotations to DAP command handlers

Replace dict[str, Any] parameters with specific TypedDict types
for better type safety and IDE support in DAP protocol handling.
```

```
Refactor handle_loaded_sources to reduce complexity

Extract helper functions for module source collection to eliminate
"too many branches" warning and improve maintainability.
```

**Avoid these patterns:**
- ❌ `Fix stuff` (too vague)
- ❌ `Update multiple files with various changes` (too broad)
- ❌ `WIP` or `temp` commits (unless clearly marked for rebasing)

### Preparing Changes for Commit

1. **Review your changes:**
	 ```bash
	 git status
	 git diff
	 ```

2. **Stage changes selectively:**
	 ```bash
	 # Stage specific files
	 git add dapper/protocol/messages.py dapper/protocol/requests.py dapper/shared/command_handlers.py
    
	 # Or stage interactively
	 git add -p
	 ```

3. **Verify staged changes:**
	 ```bash
	 git diff --staged
	 ```

4. **Run tests before committing:**
	 ```bash
	 uv run pytest
	 uv run ruff check .
	 ```

5. **Commit with descriptive message:**
	 ```bash
	 git commit -m "Brief summary of changes

	 Optional longer description explaining the motivation
	 and implementation details if needed."
	 ```

### Branching Strategy

- Use descriptive branch names: `feature/add-exception-handling`, `fix/memory-leak`, `refactor/command-handlers`
- Keep branches focused on single features or fixes
- Rebase or squash commits when merging to maintain clean history

### Before Submitting Changes

- [ ] All tests pass: `uv run pytest`
- [ ] Code passes linting: `uv run ruff check .`
- [ ] Changes are properly documented
- [ ] Commit messages are clear and descriptive
- [ ] Each commit represents a logical unit of work

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

## Project Policies

These are current, informal policies the team follows during development.

- API stability: Don't worry about backward compatibility of internal
	interfaces when making changes — there are no outside users right now.
	This means it's acceptable to change function/method signatures,
	rename internal helpers, or move responsibilities between modules
	without maintaining deprecated shims. Still aim to keep changes
	well-documented in commit messages and update tests accordingly.

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

Please follow the Git workflow guidelines outlined above for all contributions.

1. **Create a feature branch from `main`:**
	```bash
	git checkout -b feature/your-feature-name
	```

2. **Make your changes following our commit guidelines:**
	- Keep commits atomic and focused
	- Write clear, descriptive commit messages
	- Stage and review changes before committing

3. **Add tests for new functionality:**
	```bash
	# Add tests in appropriate test_*.py files
	uv run pytest tests/test_your_feature.py
	```

4. **Ensure all quality checks pass:**
	```bash
	uv run pytest          # Run all tests
	uv run ruff check .    # Lint code
	```

5. **Submit a pull request:**
	- Reference any related issues
	- Describe the changes and their motivation
	- Ensure CI passes

### Code Quality Standards

- Follow existing code style and patterns
- Add type annotations for new functions
- Update documentation for significant changes
- Maintain test coverage for new features

## Troubleshooting

### uv not found
If `uv` is not available, you can still work with the project using traditional Python tools:

```bash
# Create virtual environment
python -m venv .venv
.venv\\Scripts\\activate  # On Windows
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
-- Please see original for full details --
