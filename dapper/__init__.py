"""Dapper AI - Python Debug Adapter Protocol Implementation."""

from dapper.adapter import main as _adapter_main

__all__ = ["__version__", "main"]
__version__ = "0.1.0"


def main() -> None:
	"""Entry point that mirrors :func:`dapper.adapter.main`."""

	_adapter_main()
