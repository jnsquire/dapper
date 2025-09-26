from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from dapper.ipc_context import IPCContext

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from pathlib import Path


class DummyFile:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []

    def close(self) -> None:  # pragma: no cover - trivial
        self.calls.append("close")
        self.closed = True


class DummyConn:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True

    # Pipe API compatibility (accept returns a connection with recv/recv_bytes)
    def accept(self):  # pragma: no cover - exercised in specific test only
        return self

    def recv(self):  # pragma: no cover - not used in cleanup test
        return None

    def recv_bytes(self):  # pragma: no cover - not used in cleanup test
        return b""


@pytest.mark.parametrize("binary", [False, True])
def test_ipc_context_cleanup_closes_all(tmp_path: Path, binary: bool) -> None:
    ctx = IPCContext(binary=binary)

    # Attach dummy resources
    ctx.rfile = DummyFile()
    ctx.wfile = DummyFile()
    ctx.sock = DummyConn()
    ctx.listen_sock = DummyConn()
    ctx.pipe_conn = DummyConn()
    ctx.pipe_listener = DummyConn()

    # Create a fake unix path file
    unix_path = tmp_path / "fake.sock"
    unix_path.write_text("x")
    ctx.unix_path = unix_path

    # Sanity preconditions
    assert unix_path.exists()

    ctx.cleanup()

    # Resources should be closed / unlinked
    assert ctx.rfile.closed
    assert ctx.wfile.closed
    assert ctx.sock.closed
    assert ctx.listen_sock.closed
    assert ctx.pipe_conn.closed
    assert ctx.pipe_listener.closed
    assert not unix_path.exists(), "unix path should be removed"


def test_ipc_context_cleanup_no_resources() -> None:
    # Should not raise when everything is None
    ctx = IPCContext()
    ctx.cleanup()  # nothing attached, just ensure no exception


@pytest.mark.skipif(os.name == "nt", reason="UNIX domain socket not typical on Windows in this test")
def test_ipc_context_cleanup_real_unix_path(tmp_path: Path) -> None:
    # Light-weight integration: create a real path and ensure it is removed.
    ctx = IPCContext()
    p = tmp_path / "real.sock"
    p.touch()
    ctx.unix_path = p
    assert p.exists()
    ctx.cleanup()
    assert not p.exists()
