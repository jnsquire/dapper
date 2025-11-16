from __future__ import annotations

import json

import dapper.debug_shared as ds
from dapper.ipc_binary import unpack_header


class _PipeConn:
    def __init__(self):
        self.sent: list[bytes] = []

    def send_bytes(self, frame: bytes):  # pragma: no cover - simple container
        self.sent.append(frame)


def test_send_debug_message_event_and_logging(monkeypatch):
    # Ensure IPC disabled
    ds.state.ipc_enabled = False
    captured = []
    ds.state.on_debug_message.add_listener(
        lambda event_type, **kw: captured.append((event_type, kw))
    )

    logged = []

    def fake_debug(msg):
        logged.append(json.loads(msg))

    monkeypatch.setattr(ds.send_logger, "debug", fake_debug)

    ds.send_debug_message("response", id=1, success=True)

    assert captured == [("response", {"id": 1, "success": True})]
    assert logged == [{"event": "response", "id": 1, "success": True}]


def test_send_debug_message_binary_ipc():
    pipe = _PipeConn()
    ds.state.ipc_enabled = True
    ds.state.ipc_binary = True
    ds.state.ipc_pipe_conn = pipe
    ds.state.ipc_wfile = None  # prefer pipe

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

    # Reset state mutations for other tests
    ds.state.ipc_enabled = False
    ds.state.ipc_binary = False
    ds.state.ipc_pipe_conn = None
