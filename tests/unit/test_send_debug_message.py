from __future__ import annotations

import json

import pytest

from dapper.ipc.ipc_binary import unpack_header
from dapper.shared.command_handlers import _active_session
import dapper.shared.debug_shared as ds


class _PipeConn:
    def __init__(self):
        self.sent: list[bytes] = []

    def send_bytes(self, frame: bytes):  # pragma: no cover - simple container
        self.sent.append(frame)


@pytest.fixture
def debug_session():
    session = ds.DebugSession()
    with ds.use_session(session):
        yield session


def test_send_debug_message_requires_ipc_but_still_emits(monkeypatch, debug_session):
    """Test that send_debug_message emits to listeners but requires IPC."""
    # IPC disabled should still emit to listeners before raising
    debug_session.ipc_enabled = False
    captured = []
    debug_session.on_debug_message.add_listener(
        lambda event_type, **kw: captured.append((event_type, kw)),
    )

    # Should raise RuntimeError since IPC is mandatory
    with pytest.raises(RuntimeError, match="IPC is required"):
        ds.send_debug_message("response", id=1, success=True)

    # But listeners should still have been called before the raise
    assert captured == [("response", {"id": 1, "success": True})]


def test_send_debug_message_binary_ipc(debug_session):
    pipe = _PipeConn()
    debug_session.ipc_enabled = True
    debug_session.ipc_pipe_conn = pipe
    debug_session.ipc_wfile = None  # prefer pipe

    ds.send_debug_message("event", kind="test", value=5)

    assert len(pipe.sent) == 1
    frame = pipe.sent[0]
    # First 8 bytes header: verify unpack
    hdr = frame[:8]
    kind, length = unpack_header(hdr)
    assert kind == 1  # event frame
    payload = frame[8:]
    assert len(payload) == length
    data = json.loads(payload.decode("utf-8"))
    assert data["event"] == "event"
    assert data["kind"] == "test"
    assert data["value"] == 5


def test_handle_debug_command_skips_ack_on_send_error(monkeypatch, debug_session):
    # simulate transport.send failing after marking response_sent
    transport = debug_session.transport
    calls = []

    # record info- and warning-level messages from the command_handlers logger
    # imports below are deliberately local to avoid polluting module namespace
    from dapper.shared import command_handlers  # noqa: PLC0415

    info_logs: list[str] = []

    def _fake_log(msg, *args, **kwargs):
        try:
            info_logs.append(msg % args if args else msg)
        except Exception:
            info_logs.append(str(msg))

    monkeypatch.setattr(command_handlers.logger, "info", _fake_log)
    monkeypatch.setattr(command_handlers.logger, "warning", _fake_log)

    def broken_send(self, message_type, **kwargs):
        calls.append((message_type, kwargs))
        if message_type == "response":
            # mimic the send() logic that sets response_sent even if it later
            # throws an exception
            self.response_sent = True
        raise RuntimeError("broken")

    monkeypatch.setattr(transport, "send", broken_send.__get__(transport, type(transport)))

    # register temporary dummy handler
    from dapper.shared.command_handlers import COMMAND_HANDLERS  # noqa: PLC0415
    from dapper.shared.command_handlers import handle_debug_command  # noqa: PLC0415

    def dummy_handler(_args=None):
        session = _active_session()
        session.safe_send_response(success=True)

    # type: ignore[assignment] - handler returns None but registry expects None
    COMMAND_HANDLERS["foo"] = dummy_handler

    # ---- scenario 1: handler returns result dict but does *not* send a response ----
    # under the new contract the dispatcher should *not* auto-acknowledge; a
    # warning should be logged instead so the bug is visible.
    def ret_handler(_args=None):
        return {"success": True}

    COMMAND_HANDLERS["foo"] = ret_handler  # type: ignore[assignment] - return value dict not None, handler sends response directly
    info_logs.clear()
    handle_debug_command({"command": "foo", "id": 42})
    assert any("no response sent by handler for cmd=foo" in m for m in info_logs)
    # transport.send should never have been invoked
    assert calls == []

    # reset registry for next scenario
    COMMAND_HANDLERS.pop("foo", None)

    # ---- scenario 2: handler itself sends response and transport fails ----
    def foo_handler(_args=None):
        session = _active_session()
        session.safe_send_response(success=True)

    # type: ignore[assignment] - handler returns None but registry expects None
    COMMAND_HANDLERS["foo"] = foo_handler
    # clear previous call record and logs
    calls.clear()
    info_logs.clear()
    handle_debug_command({"command": "foo", "id": 43})
    # there should be no warning about a missing response
    assert not any("no response sent by handler for cmd=foo" in m for m in info_logs)
    # the handler-sent acknowledgement should be recorded in the log
    assert any("handler sent response for cmd=foo" in m for m in info_logs)


def test_send_debug_message_response_autofills_id_and_warns(debug_session, monkeypatch):
    """When sending a response without an explicit id we should fill it in.

    We exercise the low-level ``SessionTransport.send`` logic.  The test
    enables IPC but stubs ``require_ipc`` so that the outgoing frame is
    constructed without raising; the warning logger is patched so we can
    assert it was called.
    """
    # make IPC nominally active and prevent the actual checks from firing
    debug_session.ipc_enabled = True
    # stub out IPC requirement checks
    monkeypatch.setattr(debug_session.transport, "require_ipc", lambda: None)
    monkeypatch.setattr(debug_session.transport, "require_ipc_write_channel", lambda: None)

    # provide a write channel that records the last written frame
    class DummyWriter:
        def __init__(self):
            self.frames: list[bytes] = []

        def write(self, data):
            self.frames.append(data)

        def flush(self):
            pass

    writer = DummyWriter()
    debug_session.transport.ipc_wfile = writer

    logged: list[str] = []
    # the warning is emitted on the module logger rather than send_logger
    monkeypatch.setattr(
        ds.logger, "warning", lambda msg, *args, **kwargs: logged.append(msg % args)
    )

    # Simulate being inside a request scope with a known id and send
    with debug_session.transport.request_scope(99):
        debug_session.transport.send("response", success=True)

    assert any("Sending response without id" in msg for msg in logged)
    # inspect written frame for id
    assert writer.frames, "no frame written"
    hdr = writer.frames[-1][:8]
    _, length = unpack_header(hdr)
    payload = writer.frames[-1][8 : 8 + length]
    data = json.loads(payload.decode("utf-8"))
    assert data.get("id") == 99
    assert data.get("success") is True

    # When the current_request_id is None we still warn but don't fill an id
    logged.clear()
    writer.frames.clear()
    with debug_session.transport.request_scope(None):
        debug_session.transport.send("response", success=True)
    assert any("Sending response without id" in msg for msg in logged)
    hdr2 = writer.frames[-1][:8]
    _, length2 = unpack_header(hdr2)
    payload2 = writer.frames[-1][8 : 8 + length2]
    data2 = json.loads(payload2.decode("utf-8"))
    # when there is no current_request_id the field may be omitted
    assert data2.get("id", None) is None
    assert data2.get("success") is True
