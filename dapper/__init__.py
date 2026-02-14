"""Dapper AI - Python Debug Adapter Protocol Implementation.

Entry points
------------
``python -m dapper.adapter`` / ``dapper.main()``
    Starts the **DAP adapter** — the IDE-facing server that speaks the
    Debug Adapter Protocol.
    Accepts ``--port`` (TCP) or ``--pipe`` (named pipe) arguments.

``python -m dapper``
    Starts the **debuggee launcher** — the subprocess that runs the
    user's Python program under the debugger.  Requires ``--program``.
    Normally spawned by the adapter; you rarely need to invoke it
    directly.

These are two separate processes with different responsibilities:

- The *adapter* speaks DAP with the IDE and manages the debug session.
- The *launcher* is spawned by the adapter to run the target program.
"""

from dapper.adapter.adapter import main as _adapter_main

__all__ = ["__version__", "main"]
__version__ = "0.1.0"


def main() -> None:
    """Start the DAP adapter (IDE-facing server).

    This is the primary public entry point.  It parses CLI arguments
    (``--port`` / ``--pipe``) and starts the adapter event loop.

    Equivalent to ``python -m dapper.adapter``.

    .. note::

       ``python -m dapper`` starts the *debuggee launcher*, not the
       adapter.  See :mod:`dapper.__main__` and
       :mod:`dapper.launcher.debug_launcher`.
    """
    _adapter_main()
