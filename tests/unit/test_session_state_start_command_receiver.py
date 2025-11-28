from __future__ import annotations

import sys
import types

import dapper.shared.debug_shared as ds


class _DummyThread:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.kwargs = kwargs
        self.started = False

    def start(self):
        if self.started:
            raise AssertionError("thread started twice")
        self.started = True


def test_start_command_receiver_idempotent(monkeypatch):
    state = ds.state
    # Reset command_thread for this test
    state.command_thread = None

    # Provide dummy module with receive_debug_commands
    mod = types.ModuleType("dapper.ipc.ipc_receiver")

    def _recv():  # pragma: no cover - never actually called
        pass

    mod.receive_debug_commands = _recv  # type: ignore[attr-defined]
    
    # Patch the module in sys.modules so the import inside the function finds it
    monkeypatch.setitem(sys.modules, "dapper.ipc.ipc_receiver", mod)
    
    # Also ensure dapper.ipc has it if it's already imported
    if "dapper.ipc" in sys.modules:
        monkeypatch.setattr(sys.modules["dapper.ipc"], "ipc_receiver", mod, raising=False)

    # Monkeypatch Thread
    monkeypatch.setattr(ds.threading, "Thread", _DummyThread)

    state.start_command_receiver()
    
    # Check that command_thread was set on state
    assert state.command_thread is not None
    assert isinstance(state.command_thread, _DummyThread)
    assert state.command_thread.started is True
    
    first_thread = state.command_thread

    # Second call should not create new thread
    state.start_command_receiver()
    assert state.command_thread is first_thread


def test_start_command_receiver_failure_logged(monkeypatch, caplog):
    state = ds.state
    # Reset command_thread for this test
    state.command_thread = None
    
    # Mock module
    mod = types.ModuleType("dapper.ipc.ipc_receiver")
    mod.receive_debug_commands = lambda: None
    
    monkeypatch.setitem(sys.modules, "dapper.ipc.ipc_receiver", mod)
    if "dapper.ipc" in sys.modules:
        monkeypatch.setattr(sys.modules["dapper.ipc"], "ipc_receiver", mod, raising=False)

    # Make thread constructor raise to trigger the warning path
    def bad_thread(*_args, **_kwargs):  # simple callable matching Thread signature
        raise RuntimeError("boom")

    monkeypatch.setattr(ds.threading, "Thread", bad_thread)
    state.start_command_receiver()
    
    # Should not set command_thread
    assert state.command_thread is None
    
    # Expect a warning log mentioning failure
    found = any("Failed to start receive_debug_commands" in r.message for r in caplog.records)
    assert found
