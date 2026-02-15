import io
import json
from queue import Queue

import pytest

from dapper.ipc import ipc_receiver
from dapper.shared import debug_shared


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
    p = ipc_receiver.DapMappingProvider(mapping)
    assert p.supported_commands() == {"ok"}
    assert p.can_handle("ok")
    res = p.handle("ok", {})
    assert isinstance(res, dict)
    assert res.get("success") is True

    # callable returning None (no response)
    def noreply_handler(_args):
        return None

    mapping = {"noreply": noreply_handler}
    p = ipc_receiver.DapMappingProvider(mapping)
    assert p.handle("noreply", {}) is None

    # non-callable mapping entry
    mapping = {"bad": 123}
    p = ipc_receiver.DapMappingProvider(mapping)
    out = p.handle("bad", {})
    assert isinstance(out, dict)
    assert out.get("success") is False


def test_receive_debug_commands_ipc():
    # prepare explicit session
    session = debug_shared.DebugSession()
    session.is_terminated = False
    session.ipc_enabled = True
    session.command_queue = Queue()

    # fake reader that returns a JSON line
    cmd = {"command": "dummy", "seq": 1}
    line = json.dumps(cmd) + "\n"

    # use StringIO which implements TextIOBase for typing compatibility
    session.ipc_rfile = io.StringIO(line)

    class DummyLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    # run receiver - it will queue the command, then encounter EOF
    # which triggers exit_func(0) -> SystemExit in test mode
    with pytest.raises(SystemExit):
        ipc_receiver.receive_debug_commands(session=session)

    # queue should have exactly one item (no double-dispatch)
    assert not session.command_queue.empty()
    got = session.command_queue.get_nowait()
    assert got["command"] == "dummy"
    assert session.command_queue.empty()


def test_process_queued_commands(monkeypatch):
    session = debug_shared.DebugSession()
    session.command_queue = Queue()
    session.command_queue.put({"command": "a"})
    session.command_queue.put({"command": "b"})

    called = []

    def fake_dispatch(c):
        called.append(c)

    monkeypatch.setattr(session, "dispatch_debug_command", fake_dispatch)

    ipc_receiver.process_queued_commands(session=session)
    assert len(called) == 2
    assert session.command_queue.empty()


def test_receive_debug_commands_requires_ipc():
    """Test that receive_debug_commands raises RuntimeError when IPC is not enabled."""
    session = debug_shared.DebugSession()
    session.is_terminated = False
    session.ipc_enabled = False
    session.ipc_rfile = None

    # Should raise RuntimeError since IPC is mandatory
    with pytest.raises(RuntimeError, match="IPC is required"):
        ipc_receiver.receive_debug_commands(session=session)


def test_receive_debug_commands_malformed_json_ipc(monkeypatch):
    session = debug_shared.DebugSession()
    session.is_terminated = False
    session.ipc_enabled = True
    session.command_queue = Queue()

    # malformed JSON line
    line = "{ not-a-json }\n"
    session.ipc_rfile = io.StringIO(line)

    called = []

    def fake_send(event_type, **kwargs):
        # capture the error message and stop the loop
        called.append((event_type, kwargs))
        session.is_terminated = True

    # patch the module-level send_debug_message used in receive_debug_commands
    monkeypatch.setattr(ipc_receiver, "send_debug_message", fake_send)

    ipc_receiver.receive_debug_commands(session=session)

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

    p = ipc_receiver.DapMappingProvider(BadMapping())
    assert p.supported_commands() == set()

    # missing key (mapping.get returns None) should be treated as unknown
    mapping = {}
    p2 = ipc_receiver.DapMappingProvider(mapping)
    out = p2.handle("not-there", {})
    assert isinstance(out, dict)
    assert out.get("success") is False


def test_dap_mapping_provider_handle_raises():
    # handler that raises should propagate the exception from handle
    def boom(_):
        msg = "boom"
        raise ValueError(msg)

    mapping = {"boom": boom}
    p = ipc_receiver.DapMappingProvider(mapping)
    with pytest.raises(ValueError, match="boom"):
        p.handle("boom", {})
