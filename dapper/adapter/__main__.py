"""Dapper DAP adapter — ``python -m dapper.adapter``.

This module is the entry point for the **DAP adapter**, the IDE-facing
server that speaks the Debug Adapter Protocol.  It listens for connections
from an IDE (e.g. VS Code) over TCP (``--port``) or a named pipe
(``--pipe``) and manages the debug session.

Usage::

    python -m dapper.adapter --port 4711
    python -m dapper.adapter --pipe debug_pipe

.. note::

   This is **not** the debuggee launcher.  The adapter spawns the
   launcher internally via ``python -m dapper.launcher.debug_launcher``.
   To run the launcher directly (rare), use ``python -m dapper``.
"""

from dapper.adapter.adapter import main

if __name__ == "__main__":
    main()
