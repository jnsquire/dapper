"""Pytest-style tests for the Debug Adapter entry point.

Converted from unittest.TestCase to plain pytest functions with
fixtures and parametrization to reduce boilerplate.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack
from contextlib import suppress
from typing import TYPE_CHECKING
from typing import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.adapter import main
from dapper.adapter import start_server

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_debug_server():
    """Patch DebugAdapterServer & return (server_cls, instance)."""
    with patch("dapper.adapter.DebugAdapterServer") as server_cls:
        instance = MagicMock()

        class AsyncCallRecorder:
            def __init__(self, side_effect=None, return_value=None):
                self.calls = []
                self.await_count = 0
                self.side_effect = side_effect
                self.return_value = return_value

            async def __call__(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                self.await_count += 1
                if isinstance(self.side_effect, Exception):
                    raise self.side_effect
                if callable(self.side_effect):
                    return self.side_effect(*args, **kwargs)
                return self.return_value

            def assert_awaited_once(self):
                assert self.await_count == 1

            def assert_called_once_with(self, *args, **kwargs):
                assert len(self.calls) == 1
                assert self.calls[0] == (args, kwargs)

        instance.start = AsyncCallRecorder(return_value=None)
        server_cls.return_value = instance
        yield server_cls, instance


# ---------------------------------------------------------------------------
# start_server tests (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_server_tcp(mock_debug_server):
    server_cls, server_instance = mock_debug_server
    with patch("dapper.adapter.TCPServerConnection") as tcp_cls:
        conn_instance = MagicMock()
        tcp_cls.return_value = conn_instance

        await start_server("tcp", host="localhost", port=4711)
        # Explicitly close any created server sockets to avoid leaking
        inst = server_instance
        try:
            srv = getattr(inst, "connection", None)
            if srv and getattr(srv, "server", None):
                srv.server.close()
                await srv.server.wait_closed()
        except Exception:
            pass

        tcp_cls.assert_called_once_with(host="localhost", port=4711)
        server_cls.assert_called_once_with(conn_instance)
        server_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_server_pipe_custom_name(mock_debug_server):
    server_cls, server_instance = mock_debug_server
    with patch("dapper.adapter.NamedPipeServerConnection") as pipe_cls:
        conn_instance = MagicMock()
        pipe_cls.return_value = conn_instance

        await start_server("pipe", pipe_name="custom_pipe")
        inst = server_instance
        try:
            srv = getattr(inst, "connection", None)
            if srv and getattr(srv, "server", None):
                srv.server.close()
                await srv.server.wait_closed()
        except Exception:
            pass

        pipe_cls.assert_called_once_with(pipe_name="custom_pipe")
        server_cls.assert_called_once_with(conn_instance)
        server_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_server_pipe_default_name(mock_debug_server):
    server_cls, server_instance = mock_debug_server
    with patch("dapper.adapter.NamedPipeServerConnection") as pipe_cls:
        conn_instance = MagicMock()
        pipe_cls.return_value = conn_instance

        await start_server("pipe")
        inst = server_instance
        try:
            srv = getattr(inst, "connection", None)
            if srv and getattr(srv, "server", None):
                srv.server.close()
                await srv.server.wait_closed()
        except Exception:
            pass

        pipe_cls.assert_called_once()
        # default name applied inside function
        assert pipe_cls.call_args.kwargs.get("pipe_name") == "dapper_debug_pipe"
        server_cls.assert_called_once_with(conn_instance)
        server_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_server_unknown_connection_type():
    with patch("dapper.adapter.logger") as mock_logger:
        await start_server("unknown")
        # adapter uses logger.error with printf-style formatting
        mock_logger.error.assert_called_once_with("Unknown connection type: %s", "unknown")


# ---------------------------------------------------------------------------
# main() tests - exercise argument parsing & flow control
# ---------------------------------------------------------------------------


def _run_main_with_args(
    args: Iterable[str],
    *,
    run_side_effect: Callable | Exception | None = None,
    patch_start: bool = True,
):
    """Utility to invoke main() with patched sys.argv & asyncio.run.

    run_side_effect:
        - callable(coro) -> value : custom implementation
        - Exception instance       : raise inside patched asyncio.run
    - None : default -> actually run the coroutine in a temp loop
    patch_start: whether to patch start_server (avoids real network code)
    """
    full_argv = ["adapter.py", *args]

    def default_run(coro):
        # Run coroutine to completion in a fresh loop to avoid leaking tasks
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()

    with ExitStack() as stack:
        stack.enter_context(patch("sys.argv", full_argv))

        if patch_start:

            async def fake_start(*_a, **_kw):  # pragma: no cover - trivial
                return None

            stack.enter_context(patch("dapper.adapter.start_server", new=fake_start))

        if isinstance(run_side_effect, Exception):

            def raise_exc(_coro):  # pragma: no cover - error path
                # Prevent 'coroutine was never awaited' warning by closing
                with suppress(Exception):
                    _coro.close()  # type: ignore[attr-defined]
                raise run_side_effect

            stack.enter_context(patch("dapper.adapter.asyncio.run", new=raise_exc))
        elif callable(run_side_effect):
            stack.enter_context(patch("dapper.adapter.asyncio.run", new=run_side_effect))
        else:
            stack.enter_context(patch("dapper.adapter.asyncio.run", new=default_run))

        main()


def test_main_tcp_connection():
    with ExitStack() as stack:
        stack.enter_context(patch("dapper.adapter.logger"))

        async def fake(*_a, **_kw):  # pragma: no cover - trivial
            return None

        stack.enter_context(patch("dapper.adapter.start_server", new=fake))
        calls = []

        def run_recorder(coro):
            calls.append(coro)
            # actually await to avoid warnings
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        _run_main_with_args(
            ["--port", "4711"],
            run_side_effect=run_recorder,
            patch_start=False,
        )
        assert len(calls) == 1
    # Patched with concrete function; no mock assertions applicable.


def test_main_pipe_connection():
    with patch("dapper.adapter.logger"):
        _run_main_with_args(["--pipe", "test_pipe"])


def test_main_with_host_argument():
    with ExitStack() as stack:
        stack.enter_context(patch("dapper.adapter.logger"))

        async def fake(*_a, **_kw):  # pragma: no cover - trivial
            return None

        stack.enter_context(patch("dapper.adapter.start_server", new=fake))
        _run_main_with_args(["--pipe", "x", "--host", "127.0.0.1"], patch_start=False)
    # Patched with concrete function; no mock assertions applicable.


def test_main_log_level():
    with patch("dapper.adapter.logger"), patch("dapper.adapter.logging.getLogger") as get_logger:
        mock_root = MagicMock()
        get_logger.return_value = mock_root
        _run_main_with_args(["--port", "4711", "--log-level", "DEBUG"])
        mock_root.setLevel.assert_called_once_with(logging.DEBUG)


def test_main_no_connection_args():
    with patch("dapper.adapter.logger"), pytest.raises(SystemExit):
        _run_main_with_args([])


def test_main_keyboard_interrupt():
    with patch("dapper.adapter.logger") as mock_logger:
        # Provide a replacement for asyncio.run that immediately raises,
        # ensuring no coroutine returned by start_server is left un-awaited.
        def raise_kb(_coro):  # pragma: no cover - simple path
            # close the coroutine to avoid RuntimeWarning
            with suppress(Exception):
                _coro.close()  # type: ignore[attr-defined]
            raise KeyboardInterrupt

        _run_main_with_args(["--port", "4711"], run_side_effect=raise_kb)
        mock_logger.info.assert_called_once_with("Debug adapter stopped by user")
