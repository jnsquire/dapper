from __future__ import annotations

from typing import Any

import pytest

from dapper.ipc.sync_adapter import SyncConnectionAdapter


class _FakeConn:
    def __init__(self, *, fail_on_close: bool = False) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_on_close = fail_on_close

    async def accept(self) -> None:
        self.calls.append(("accept", None))

    async def read_dbgp_message(self) -> str:
        self.calls.append(("read_dbgp_message", None))
        return "dbgp"

    async def read_message(self) -> dict[str, Any]:
        self.calls.append(("read_message", None))
        return {"ok": True}

    async def write_dbgp_message(self, msg: str) -> None:
        self.calls.append(("write_dbgp_message", msg))

    async def write_message(self, message: dict[str, Any]) -> None:
        self.calls.append(("write_message", message))

    async def close(self) -> None:
        self.calls.append(("close", None))
        if self.fail_on_close:
            msg = "boom"
            raise RuntimeError(msg)


def test_sync_connection_adapter_roundtrip_methods() -> None:
    conn = _FakeConn()
    adapter = SyncConnectionAdapter(conn)
    try:
        assert adapter.accept() is None
        assert adapter.read_dbgp_message() == "dbgp"
        assert adapter.read_message() == {"ok": True}
        assert adapter.write_dbgp_message("hello") is None
        payload = {"type": "event", "event": "stopped"}
        assert adapter.write_message(payload) is None

        assert ("accept", None) in conn.calls
        assert ("read_dbgp_message", None) in conn.calls
        assert ("read_message", None) in conn.calls
        assert ("write_dbgp_message", "hello") in conn.calls
        assert ("write_message", payload) in conn.calls
    finally:
        adapter.close()


def test_sync_connection_adapter_close_propagates_conn_close_errors() -> None:
    conn = _FakeConn(fail_on_close=True)
    adapter = SyncConnectionAdapter(conn)
    with pytest.raises(RuntimeError, match="boom"):
        adapter.close()
    assert ("close", None) in conn.calls


def test_sync_connection_adapter_run_coro_raises_when_loop_missing() -> None:
    conn = _FakeConn()
    adapter = SyncConnectionAdapter(conn)
    try:
        adapter._loop = None
        with pytest.raises(RuntimeError, match="Adapter loop not started"):
            adapter.read_message()
    finally:
        # Ensure no background thread leak from setup.
        adapter._loop = None
        if adapter._thread is not None:
            adapter._thread.join(timeout=1.0)
