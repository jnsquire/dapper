from __future__ import annotations

import json

import pytest

from dapper.ipc.ipc_binary import unpack_header
import dapper.shared.debug_shared as ds


class _PipeConn:
    def __init__(self):
        self.sent: list[bytes] = []

    def send_bytes(self, frame: bytes):  # pragma: no cover - simple container
        self.sent.append(frame)


def test_send_debug_message_requires_ipc_but_still_emits(monkeypatch):
    """Test that send_debug_message emits to listeners but requires IPC."""
    # IPC disabled should still emit to listeners before raising
    ds.state.ipc_enabled = False
    captured = []
    ds.state.on_debug_message.add_listener(
        lambda event_type, **kw: captured.append((event_type, kw))
    )

    logged = []

    def fake_debug(msg):
        logged.append(json.loads(msg))

    monkeypatch.setattr(ds.send_logger, "debug", fake_debug)

    # Should raise RuntimeError since IPC is mandatory
    with pytest.raises(RuntimeError, match="IPC is required"):
        ds.send_debug_message("response", id=1, success=True)

    # But listeners should still have been called before the raise
    assert captured == [("response", {"id": 1, "success": True})]


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
