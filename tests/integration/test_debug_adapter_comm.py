import io
import json
from queue import Queue

import pytest

from dapper.ipc import ipc_receiver
from dapper.ipc.ipc_binary import pack_frame
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

    # Build a binary DP-frame for the command
    cmd = {"command": "dummy", "seq": 1}
    payload = json.dumps(cmd).encode("utf-8")
    frame = pack_frame(2, payload)  # kind=2 = command

    # use BytesIO for binary IPC
    session.ipc_rfile = io.BytesIO(frame)
    session.ipc_wfile = io.BytesIO()  # dispatch may send responses

    # run receiver - it will read one frame, dispatch, then encounter EOF
    # which triggers exit_if_alive(0) -> SystemExit in test mode
    with pytest.raises(SystemExit):
        ipc_receiver.receive_debug_commands(session=session)

    # queue should have exactly one item
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


def test_receive_debug_commands_malformed_json_ipc():
    session = debug_shared.DebugSession()
    session.is_terminated = False
    session.ipc_enabled = True
    session.command_queue = Queue()

    # Build a binary frame with malformed JSON payload
    bad_payload = b"{ not-a-json }"
    frame = pack_frame(2, bad_payload)  # kind=2 = command
    session.ipc_rfile = io.BytesIO(frame)

    called = []

    def fake_send(event_type, **kwargs):
        # capture the error message and stop the loop
        called.append((event_type, kwargs))
        session.is_terminated = True

    ipc_receiver.receive_debug_commands(session=session, error_sender=fake_send)

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
