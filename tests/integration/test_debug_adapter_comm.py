import io
import json
from queue import Queue

import pytest

from dapper.adapter import debug_adapter_comm as dac


class DummyLock:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return None


def test_dap_mapping_provider_handle_variants():
    # callable returning success dict
    def ok_handler(_args):
        return {"success": True, "body": {}}

    mapping = {"ok": ok_handler}
    p = dac.DapMappingProvider(mapping)
    assert p.supported_commands() == {"ok"}
    assert p.can_handle("ok")
    res = p.handle("ok", {})
    assert isinstance(res, dict)
    assert res.get("success") is True

    # callable returning None (no response)
    def noreply_handler(_args):
        return None

    mapping = {"noreply": noreply_handler}
    p = dac.DapMappingProvider(mapping)
    assert p.handle("noreply", {}) is None

    # non-callable mapping entry
    mapping = {"bad": 123}
    p = dac.DapMappingProvider(mapping)
    out = p.handle("bad", {})
    assert isinstance(out, dict)
    assert out.get("success") is False


def test_receive_debug_commands_ipc(monkeypatch):
    # prepare fake state
    s = dac.state
    s.is_terminated = False
    s.ipc_enabled = True
    s.command_queue = Queue()

    # fake reader that returns a DBGCMD line once
    cmd = {"command": "dummy", "seq": 1}
    line = "DBGCMD:" + json.dumps(cmd) + "\n"

    # use StringIO which implements TextIOBase for typing compatibility
    s.ipc_rfile = io.StringIO(line)

    called = []

    def fake_dispatch(c):
        called.append(c)
        # ensure the receive loop exits after first command
        s.is_terminated = True

    class DummyLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(s, "dispatch_debug_command", fake_dispatch)

    # run receiver (should process one command and return)
    dac.receive_debug_commands()
    assert called
    assert called[0]["command"] == "dummy"
    # queue should have at least one item
    assert not s.command_queue.empty()
    got = s.command_queue.get_nowait()
    assert got["command"] == "dummy"


def test_process_queued_commands(monkeypatch):
    s = dac.state
    s.command_queue = Queue()
    s.command_queue.put({"command": "a"})
    s.command_queue.put({"command": "b"})

    called = []

    def fake_dispatch(c):
        called.append(c)

    monkeypatch.setattr(s, "dispatch_debug_command", fake_dispatch)

    dac.process_queued_commands()
    assert len(called) == 2
    assert s.command_queue.empty()


def test_receive_debug_commands_requires_ipc():
    """Test that receive_debug_commands raises RuntimeError when IPC is not enabled."""
    s = dac.state
    # Save original state
    orig_is_terminated = s.is_terminated
    orig_ipc_enabled = s.ipc_enabled
    orig_ipc_rfile = s.ipc_rfile

    try:
        s.is_terminated = False
        s.ipc_enabled = False
        s.ipc_rfile = None

        # Should raise RuntimeError since IPC is mandatory
        with pytest.raises(RuntimeError, match="IPC is required"):
            dac.receive_debug_commands()
    finally:
        # Restore original state
        s.is_terminated = orig_is_terminated
        s.ipc_enabled = orig_ipc_enabled
        s.ipc_rfile = orig_ipc_rfile


def test_receive_debug_commands_malformed_json_ipc(monkeypatch):
    s = dac.state
    s.is_terminated = False
    s.ipc_enabled = True
    s.command_queue = Queue()

    # malformed JSON after DBGCMD:
    line = "DBGCMD:{ not-a-json }\n"
    s.ipc_rfile = io.StringIO(line)

    called = []

    def fake_send(event_type, **kwargs):
        # capture the error message and stop the loop
        called.append((event_type, kwargs))
        s.is_terminated = True

    # patch the module-level send_debug_message used in receive_debug_commands
    monkeypatch.setattr(dac, "send_debug_message", fake_send)

    dac.receive_debug_commands()

    assert called, "send_debug_message was not called for malformed JSON"
    ev, kw = called[0]
    assert ev == "error"
    assert "Error receiving command" in kw.get("message", "")


def test_dap_mapping_provider_supported_commands_errors_and_missing():
    # mapping-like object whose keys() raises should be handled gracefully
    class BadMapping:
        def keys(self):
            msg = "no keys"
            raise RuntimeError(msg)

    p = dac.DapMappingProvider(BadMapping())
    assert p.supported_commands() == set()

    # missing key (mapping.get returns None) should be treated as unknown
    mapping = {}
    p2 = dac.DapMappingProvider(mapping)
    out = p2.handle("not-there", {})
    assert isinstance(out, dict)
    assert out.get("success") is False


def test_dap_mapping_provider_handle_raises():
    # handler that raises should propagate the exception from handle
    def boom(_):
        msg = "boom"
        raise ValueError(msg)

    mapping = {"boom": boom}
    p = dac.DapMappingProvider(mapping)
    with pytest.raises(ValueError, match="boom"):
        p.handle("boom", {})
