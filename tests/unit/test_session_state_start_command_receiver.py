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
    # Remove flag if set from previous tests
    if hasattr(state, "_command_thread_started"):
        delattr(state, "_command_thread_started")

    # Provide dummy module with receive_debug_commands
    mod = types.ModuleType("dapper.debug_adapter_comm")

    def _recv():  # pragma: no cover - never actually called
        pass

    mod.receive_debug_commands = _recv  # type: ignore[attr-defined]
    sys.modules["dapper.debug_adapter_comm"] = mod

    # Monkeypatch Thread
    monkeypatch.setattr(ds.threading, "Thread", _DummyThread)

    state.start_command_receiver()
    assert getattr(state, "_command_thread_started", False) is True
    # Second call should not create new thread (would raise inside _DummyThread)
    state.start_command_receiver()

    # Cleanup sys.modules entry
    sys.modules.pop("dapper.debug_adapter_comm", None)


def test_start_command_receiver_failure_logged(monkeypatch, caplog):
    state = ds.state
    # Force import failure by removing module and making import raise
    if hasattr(state, "_command_thread_started"):
        delattr(state, "_command_thread_started")

    # Make thread constructor raise to trigger the warning path
    def bad_thread():  # simple callable matching Thread signature for our test
        raise RuntimeError("boom")

    monkeypatch.setattr(ds.threading, "Thread", bad_thread)
    state.start_command_receiver()
    # Should not set started flag
    assert not getattr(state, "_command_thread_started", False)
    # Expect a warning log mentioning failure
    found = any("Failed to start receive_debug_commands" in r.message for r in caplog.records)
    assert found
