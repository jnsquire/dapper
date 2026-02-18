from __future__ import annotations

import logging

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


def test_is_expected_loop_shutdown_error_matches_runtime_error() -> None:
    assert _is_expected_loop_shutdown_error(
        RuntimeError("Event loop stopped before Future completed.")
    )
    assert not _is_expected_loop_shutdown_error(RuntimeError("other runtime error"))
    assert not _is_expected_loop_shutdown_error(
        ValueError("Event loop stopped before Future completed.")
    )


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
