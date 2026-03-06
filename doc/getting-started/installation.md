# Installation

This page covers installing Dapper for end users. If you are setting up a development environment, see the [Development Setup](../development/setup.md) guide instead.

## Requirements

- Python 3.9 or newer
- `pip` (included with Python)

## Install via pip

```bash
pip install dapper
```

If you are working from the repository before a packaged release is available, install from source instead.

## Install from Source

```bash
# Clone the repository
git clone https://github.com/jnsquire/dapper.git
cd dapper

# Install the project and development dependencies
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
