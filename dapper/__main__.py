"""Dapper debuggee launcher — ``python -m dapper``.

This module is the entry point for the **debuggee launcher**, the subprocess
that runs the user's Python program under the debugger.  It is spawned by
the DAP adapter and communicates with it over IPC.

.. important::

   ``python -m dapper`` starts the *launcher*, **not** the DAP adapter.
   To start the adapter (the IDE-facing server), use::

       python -m dapper.adapter --port 4711

   Or call :func:`dapper.main` / :func:`dapper.adapter.adapter.main`.
"""

from dapper.launcher.debug_launcher import main

if __name__ == "__main__":
    main()
