from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import dapper.debug_shared as ds


def test_setup_process_state_ipc_failure(caplog):
    state = ds.state

    # Provide args that request IPC so the code tries to import launcher_ipc
    args = SimpleNamespace(
        ipc="socket",
        ipc_host="127.0.0.1",
        ipc_port=0,
        ipc_path=None,
        stop_on_entry=False,
        no_debug=False,
    )

    # Force import failure of launcher_ipc helpers
    def bad_setup():
        raise RuntimeError("boom")

    # Insert fake module with failing functions
    mod = types.ModuleType("dapper.launcher_ipc")
    mod._setup_ipc_pipe = bad_setup  # type: ignore[attr-defined]
    mod._setup_ipc_socket = bad_setup  # type: ignore[attr-defined]
    sys.modules["dapper.launcher_ipc"] = mod

    # Clear prior flag
    state.ipc_enabled = True  # will be set False on failure path

    state.setup_process_state(args)

    # Should have logged the failure and disabled ipc
    assert state.ipc_enabled is False
    found = any("IPC setup failed" in r.message for r in caplog.records)
    assert found

    # Cleanup
    sys.modules.pop("dapper.launcher_ipc", None)
