from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from dapper.ipc.ipc_manager import IPCManager
from dapper.ipc.ipc_manager import _is_expected_loop_shutdown_error


class _AcceptShutdownConn:
    async def accept(self) -> None:
        raise RuntimeError("Event loop stopped before Future completed.")


class _ReadShutdownConn:
    async def read_message(self):
        raise RuntimeError("Event loop stopped before Future completed.")


class _ReadErrorConn:
    async def read_message(self):
        raise ValueError("boom")


class _AcceptCancelledConn:
    async def accept(self) -> None:
        raise asyncio.CancelledError


class _ReadCancelledConn:
    async def read_message(self):
        raise asyncio.CancelledError


class _AcceptSystemExitConn:
    async def accept(self) -> None:
        raise SystemExit


class _SyncCloseConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _AsyncCloseConn:
    def __init__(self) -> None:
        self.close = AsyncMock(side_effect=self._close)
        self.closed = False

    async def _close(self) -> None:
        self.closed = True


class _IdleThread:
    def is_alive(self) -> bool:
        return False


def test_is_expected_loop_shutdown_error_matches_runtime_error() -> None:
    assert _is_expected_loop_shutdown_error(
        RuntimeError("Event loop stopped before Future completed."),
    )
    assert not _is_expected_loop_shutdown_error(RuntimeError("other runtime error"))
    assert not _is_expected_loop_shutdown_error(
        ValueError("Event loop stopped before Future completed."),
    )


def test_is_expected_loop_shutdown_error_matches_cancelled_and_system_exit() -> None:
    assert _is_expected_loop_shutdown_error(asyncio.CancelledError())
    assert _is_expected_loop_shutdown_error(SystemExit())


def test_read_messages_accept_shutdown_does_not_log_error(caplog) -> None:
    manager = IPCManager()
    manager._connection = _AcceptShutdownConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = True

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error accepting IPC connection" not in caplog.text


def test_read_messages_read_shutdown_does_not_log_error(caplog) -> None:
    manager = IPCManager()
    manager._connection = _ReadShutdownConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = False

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error reading IPC message" not in caplog.text


def test_read_messages_read_real_error_logs(caplog) -> None:
    manager = IPCManager()
    manager._connection = _ReadErrorConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = False

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error reading IPC message" in caplog.text


def test_read_messages_accept_cancelled_does_not_log_error(caplog) -> None:
    manager = IPCManager()
    manager._connection = _AcceptCancelledConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = True

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error accepting IPC connection" not in caplog.text


def test_read_messages_read_cancelled_does_not_log_error(caplog) -> None:
    manager = IPCManager()
    manager._connection = _ReadCancelledConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = False

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error reading IPC message" not in caplog.text


def test_read_messages_accept_system_exit_does_not_log_error(caplog) -> None:
    manager = IPCManager()
    manager._connection = _AcceptSystemExitConn()  # pyright: ignore[reportAttributeAccessIssue]
    manager._message_handler = lambda _message: None
    manager._enabled = True
    manager._should_accept = True

    with caplog.at_level(logging.ERROR):
        manager._read_messages()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Error accepting IPC connection" not in caplog.text


def test_cleanup_closes_sync_connection_and_resets_state() -> None:
    manager = IPCManager()
    conn = _SyncCloseConn()
    manager._connection = conn  # pyright: ignore[reportAttributeAccessIssue]
    manager._enabled = True
    manager._message_handler = lambda _message: None
    manager._reader_thread = _IdleThread()  # pyright: ignore[reportAttributeAccessIssue]

    manager.cleanup()

    assert conn.closed is True
    assert manager.connection is None
    assert manager.is_enabled is False
    assert manager._message_handler is None
    assert manager._reader_thread is None


@pytest.mark.asyncio
async def test_acleanup_awaits_async_close_and_resets_state() -> None:
    manager = IPCManager()
    conn = _AsyncCloseConn()
    manager._connection = conn  # pyright: ignore[reportAttributeAccessIssue]
    manager._enabled = True
    manager._message_handler = lambda _message: None
    manager._reader_thread = _IdleThread()  # pyright: ignore[reportAttributeAccessIssue]

    await manager.acleanup()

    conn.close.assert_awaited_once()
    assert conn.closed is True
    assert manager.connection is None
    assert manager.is_enabled is False
    assert manager._message_handler is None
    assert manager._reader_thread is None
