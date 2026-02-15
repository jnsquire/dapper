from __future__ import annotations

import os

from dapper.shared import debug_shared as ds


class _DummyProvider:
    def can_handle(self, _command: str) -> bool:
        return False

    def handle(self, _session, _command: str, _arguments, _full_command):
        return None


def test_reset_preserves_default_state_identity() -> None:
    before = ds.state
    after = ds.SessionState.reset()

    assert before is after
    assert ds.state is after


def test_sessionstate_constructor_is_independent_from_default_state() -> None:
    explicit = ds.SessionState()
    assert explicit is not ds.state


def test_reset_reinitializes_mutable_fields() -> None:
    s = ds.state

    # Populate mutable state with non-default values
    s.debugger = object()
    s.stop_at_entry = True
    s.no_debug = True
    s.command_queue.put({"command": "x"})
    s.is_terminated = True
    s.ipc_enabled = True
    s.ipc_binary = True
    s.ipc_sock = object()
    s.ipc_rfile = object()
    s.ipc_wfile = object()
    s.ipc_pipe_conn = object()
    s.command_thread = object()  # sentinel; type is intentionally loose in tests

    provider = _DummyProvider()
    s.register_command_provider(provider, priority=7)

    ref = s.get_or_create_source_ref("/tmp/test_reset.py", "test_reset.py")
    assert ref >= 1
    assert s.source_references

    # Add an event listener to verify emitter reset
    calls: list[tuple[str, dict]] = []

    def _listener(event_type: str, **kwargs) -> None:
        calls.append((event_type, kwargs))

    s.on_debug_message.add_listener(_listener)

    s.set_exit_func(lambda _code: None)
    s.set_exec_func(lambda _path, _args: None)

    # Reset singleton state
    reset_state = ds.SessionState.reset()

    assert reset_state.debugger is None
    assert reset_state.stop_at_entry is False
    assert reset_state.no_debug is False
    assert reset_state.command_queue.empty()
    assert reset_state.is_terminated is False
    assert reset_state.ipc_enabled is False
    assert reset_state.ipc_binary is False
    assert reset_state.ipc_sock is None
    assert reset_state.ipc_rfile is None
    assert reset_state.ipc_wfile is None
    assert reset_state.ipc_pipe_conn is None
    assert reset_state.command_thread is None
    assert reset_state._providers == []
    assert reset_state.source_references == {}
    assert reset_state._path_to_ref == {}

    # Source ref counter should restart at 1
    assert reset_state.get_or_create_source_ref("/tmp/test_reset_2.py") == 1

    # Event listeners should be cleared by replacing emitter instance
    reset_state.on_debug_message.emit("probe", ok=True)
    assert calls == []

    # Hooks should be restored to defaults
    assert reset_state.exec_func is os.execv
    assert callable(reset_state.exit_func)
