from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dapper.ipc.ipc_binary import unpack_header
from dapper.shared.command_handlers import _active_session
import dapper.shared.debug_shared as ds
from dapper.utils.logging_levels import TRACE


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
    assert data["body"]["kind"] == "test"
    assert data["body"]["value"] == 5


def test_send_debug_message_does_not_append_directly_to_session_log(
    tmp_path, monkeypatch, debug_session
):
    debug_session.ipc_enabled = True
    debug_session.transport.session_log_file = str(tmp_path / "session.log")

    monkeypatch.setattr(debug_session.transport, "require_ipc", lambda: None)
    monkeypatch.setattr(debug_session.transport, "require_ipc_write_channel", lambda: None)

    class DummyWriter:
        def __init__(self):
            self.frames: list[bytes] = []

        def write(self, data):
            self.frames.append(data)

        def flush(self):
            pass

    writer = DummyWriter()
    debug_session.transport.ipc_wfile = writer

    records: list[tuple[str, tuple[object, ...]]] = []

    def _capture(msg, *args, **kwargs):
        records.append((msg, args))

    monkeypatch.setattr(ds.transport_logger, "debug", _capture)

    with debug_session.transport.request_scope(7):
        debug_session.transport.send("response", success=True)

    assert writer.frames
    assert not (tmp_path / "session.log").exists()
    assert records == [
        (
            "[id=%s] transport.send %s",
            (7, "response id=7 success=True"),
        )
    ]


def test_handle_debug_command_skips_ack_on_send_error(monkeypatch, debug_session):
    # simulate transport.send failing after marking response_sent
    transport = debug_session.transport
    calls = []

    # record info- and warning-level messages from the command_handlers logger
    # imports below are deliberately local to avoid polluting module namespace
    from dapper.shared import command_handlers

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
    from dapper.shared.command_handlers import COMMAND_HANDLERS
    from dapper.shared.command_handlers import handle_debug_command

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
    assert any("cmd=foo response=missing" in m for m in info_logs)
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
    assert not any("cmd=foo response=missing" in m for m in info_logs)
    # the dispatcher should emit a single concise acknowledgement line
    assert any("cmd=foo response=sent" in m for m in info_logs)


def test_handle_debug_command_logs_full_trace_messages(monkeypatch, debug_session):
    from dapper.shared import command_handlers

    debug_session.ipc_enabled = True
    monkeypatch.setattr(debug_session.transport, "require_ipc", lambda: None)
    monkeypatch.setattr(debug_session.transport, "require_ipc_write_channel", lambda: None)

    class DummyWriter:
        def __init__(self):
            self.frames: list[bytes] = []

        def write(self, data):
            self.frames.append(data)

        def flush(self):
            pass

    writer = DummyWriter()
    debug_session.transport.ipc_wfile = writer

    trace_logs: list[str] = []

    def _capture_trace(level, msg, *args, **kwargs):
        if level == TRACE:
            trace_logs.append(msg % args if args else str(msg))

    monkeypatch.setattr(command_handlers.logger, "isEnabledFor", lambda level: level >= TRACE)
    monkeypatch.setattr(command_handlers.logger, "log", _capture_trace)

    from dapper.shared.command_handlers import COMMAND_HANDLERS
    from dapper.shared.command_handlers import handle_debug_command

    def foo_handler(_args=None):
        session = _active_session()
        session.safe_send_response(success=True, body={"status": "ok"})

    COMMAND_HANDLERS["foo"] = foo_handler
    try:
        handle_debug_command(
            {"command": "foo", "id": 43, "arguments": {"alpha": 1}},
            session=debug_session,
        )
    finally:
        COMMAND_HANDLERS.pop("foo", None)

    assert writer.frames
    assert trace_logs == [
        'recv {"arguments": {"alpha": 1}, "command": "foo", "id": 43}',
        'send {"body": {"status": "ok"}, "event": "response", "id": 43, "success": true}',
    ]


def test_handle_debug_command_trace_logging_suppresses_info_ack(monkeypatch, debug_session):
    from dapper.shared import command_handlers
    from dapper.shared.command_handlers import COMMAND_HANDLERS
    from dapper.shared.command_handlers import handle_debug_command

    info_logs: list[str] = []

    monkeypatch.setattr(command_handlers.logger, "isEnabledFor", lambda level: level >= TRACE)
    monkeypatch.setattr(command_handlers.logger, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        command_handlers.logger,
        "info",
        lambda msg, *args, **kwargs: info_logs.append(msg % args if args else str(msg)),
    )

    def foo_handler(_args=None):
        session = _active_session()
        session.transport.response_sent = True

    COMMAND_HANDLERS["foo"] = foo_handler
    try:
        handle_debug_command({"command": "foo", "id": 43}, session=debug_session)
    finally:
        COMMAND_HANDLERS.pop("foo", None)

    assert info_logs == []


def test_agent_command_logs_are_condensed(monkeypatch, debug_session):
    from dapper.shared import command_handlers

    debug_logs: list[str] = []
    warning_logs: list[str] = []
    responses: list[dict[str, object]] = []

    def _capture_debug(msg, *args, **kwargs):
        debug_logs.append(msg % args if args else str(msg))

    def _capture_warning(msg, *args, **kwargs):
        warning_logs.append(msg % args if args else str(msg))

    frame_id = 55
    thread_id = 22
    tracker = SimpleNamespace(
        stopped_thread_ids={thread_id},
        threads={thread_id: object()},
        frames_by_thread={
            thread_id: [
                {
                    "id": frame_id,
                    "name": "worker",
                    "line": 17,
                    "source": {"path": "/tmp/worker.py"},
                }
            ]
        },
        frame_id_to_frame={
            frame_id: SimpleNamespace(
                f_locals={"value": 42},
                f_globals={"visible": "yes", "__name__": "fixture"},
            )
        },
    )
    debug_session.debugger = SimpleNamespace(
        thread_tracker=tracker,
        exception_handler=SimpleNamespace(exception_info_by_thread={}),
    )

    monkeypatch.setattr(command_handlers.logger, "debug", _capture_debug)
    monkeypatch.setattr(command_handlers.logger, "warning", _capture_warning)
    monkeypatch.setattr(
        debug_session,
        "safe_send_response",
        lambda **payload: responses.append(payload) or True,
    )
    monkeypatch.setattr(command_handlers, "_get_frame_by_index", lambda dbg, frame_index: object())
    monkeypatch.setattr(
        command_handlers,
        "_evaluate_agent_expression",
        lambda expr, frame: {"expression": expr, "result": repr(frame)},
    )
    monkeypatch.setattr(
        command_handlers,
        "evaluate_with_policy",
        lambda expression, frame: {"alpha": 1, "beta": 2},
    )

    with debug_session.transport.request_scope(99):
        command_handlers._cmd_agent_snapshot({"threadId": thread_id})
    with debug_session.transport.request_scope(100):
        command_handlers._cmd_agent_eval({"expressions": ["x", "y"], "frameIndex": 1})
    with debug_session.transport.request_scope(101):
        command_handlers._cmd_agent_inspect({"expression": "alpha", "frameIndex": 2, "depth": 2})

    assert warning_logs == []
    assert any("dapper/agentSnapshot success:" in line for line in debug_logs)
    assert any("dapper/agentEval success:" in line for line in debug_logs)
    assert any("dapper/agentInspect success:" in line for line in debug_logs)
    assert not any("entered" in line for line in debug_logs)
    assert not any("sending response" in line for line in debug_logs)
    assert not any("top frame_id" in line for line in debug_logs)
    assert len(responses) == 3


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
    # the warning is emitted on the module logger rather than the transport logger
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


def test_send_debug_message_trace_logging_suppresses_debug_summary(debug_session, monkeypatch):
    debug_session.ipc_enabled = True
    monkeypatch.setattr(debug_session.transport, "require_ipc", lambda: None)
    monkeypatch.setattr(debug_session.transport, "require_ipc_write_channel", lambda: None)

    class DummyWriter:
        def __init__(self):
            self.frames: list[bytes] = []

        def write(self, data):
            self.frames.append(data)

        def flush(self):
            pass

    writer = DummyWriter()
    debug_session.transport.ipc_wfile = writer

    trace_logs: list[str] = []
    debug_logs: list[str] = []

    monkeypatch.setattr(ds.commands_logger, "isEnabledFor", lambda level: level >= TRACE)
    monkeypatch.setattr(
        ds.commands_logger,
        "log",
        lambda level, msg, *args, **kwargs: (
            trace_logs.append(msg % args if args else str(msg)) if level == TRACE else None
        ),
    )
    monkeypatch.setattr(
        ds.transport_logger,
        "debug",
        lambda msg, *args, **kwargs: debug_logs.append(msg % args if args else str(msg)),
    )

    with debug_session.transport.request_scope(7):
        debug_session.transport.send("response", success=True)

    assert writer.frames
    assert trace_logs == ['send {"event": "response", "id": 7, "success": true}']
    assert debug_logs == []
