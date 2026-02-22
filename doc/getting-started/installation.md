# Installation

This page covers installing Dapper for end users. If you are setting up a development environment, see the [Development Setup](../development/setup.md) guide instead.

## Requirements

- Python 3.9 or newer
- `pip` (included with Python)

## Install via pip

```bash
pip install dapper
```

!!! note "TODO"
    Dapper is not yet published to PyPI. This command will work once a release is made. In the meantime, install from source (see below).

## Install from Source

```bash
# Clone the repository
git clone <repository-url>
cd dapper

# Install in editable mode with pip
pip install -e .

# Or use uv for faster dependency resolution
uv sync
```

## Verify the Installation

```bash
python -m dapper --help
```

You should see the Dapper CLI help output. If you get a `ModuleNotFoundError`, double-check that you installed into the correct Python environment.

## Next Steps

- [Quick Start](quickstart.md) — run your first debugging session
- [Async Debugging Guide](../guides/async-debugging.md) — debug asyncio applications
