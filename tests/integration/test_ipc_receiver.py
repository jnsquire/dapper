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
    # callable handler — handle() returns None; handler is responsible for
    # sending its own response via session.safe_send_response().
    called = []

    def ok_handler(_args):
        called.append("ok")

    mapping = {"ok": ok_handler}
    p = ipc_receiver.DapMappingProvider(mapping)
    assert p.supported_commands() == {"ok"}
    assert p.can_handle("ok")
    result = p.handle("ok", {})
    assert result is None
    assert called == ["ok"]

    # non-callable mapping entry — sends an error via the session when one is
    # provided; for the direct (str-session) call shape just returns None.
    mapping = {"bad": 123}
    p = ipc_receiver.DapMappingProvider(mapping)
    result = p.handle("bad", {})
    assert result is None


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
    session.ipc_wfile = io.BytesIO()

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

    # missing key (can_handle returns False, handle is not called)
    mapping = {}
    p2 = ipc_receiver.DapMappingProvider(mapping)
    assert not p2.can_handle("not-there")


def test_dap_mapping_provider_handle_raises():
    # handler that raises should propagate the exception from handle
    def boom(_):
        msg = "boom"
        raise ValueError(msg)

    mapping = {"boom": boom}
    p = ipc_receiver.DapMappingProvider(mapping)
    with pytest.raises(ValueError, match="boom"):
        p.handle("boom", {})
