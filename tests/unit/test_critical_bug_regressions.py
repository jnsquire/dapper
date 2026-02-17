"""Regression tests for critical bugs found during code review.

Each test in this module would have FAILED before the corresponding fix
and passes now. The test names reference the checklist item they cover.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import socket
import tempfile
import threading
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.config import DapperConfig
from dapper.config import DebuggeeConfig
from dapper.config.config_manager import ConfigContext
from dapper.config.config_manager import get_config
from dapper.config.config_manager import reset_config
from dapper.config.config_manager import set_config
from dapper.config.config_manager import update_config
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.breakpoint_resolver import ResolveResult
from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.launcher.launcher_ipc import SocketConnector
from tests.mocks import make_real_frame

# ---------------------------------------------------------------------------
# 1. Config manager — `global` declaration was missing
# ---------------------------------------------------------------------------


class TestConfigManagerGlobal:
    """Verify set_config / update_config / reset_config / ConfigContext
    actually persist their changes to the module-level global."""

    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def _make_valid_config(self, **overrides: Any) -> DapperConfig:
        """Create a config that passes validation."""
        defaults: dict[str, Any] = {
            "mode": "launch",
            "debuggee": DebuggeeConfig(program="/dummy/program.py"),
        }
        defaults.update(overrides)
        return DapperConfig(**defaults)

    def test_set_config_persists(self) -> None:
        """set_config should change what get_config returns."""
        new_cfg = self._make_valid_config(log_level="DEBUG")
        set_config(new_cfg)
        assert get_config() is new_cfg
        assert get_config().log_level == "DEBUG"

    def test_update_config_persists(self) -> None:
        """update_config should mutate the global config."""
        set_config(self._make_valid_config())
        original = get_config()
        update_config(log_level="WARNING")
        updated = get_config()
        assert updated.log_level == "WARNING"
        # It should still be the same object (mutated in place)
        assert updated is original

    def test_reset_config_restores_default(self) -> None:
        """reset_config should revert to DEFAULT_CONFIG."""
        set_config(self._make_valid_config(log_level="DEBUG"))
        assert get_config().log_level == "DEBUG"
        reset_config()
        assert get_config().log_level == "INFO"

    def test_config_context_applies_and_reverts(self) -> None:
        """ConfigContext should apply changes on enter and revert on exit."""
        set_config(self._make_valid_config())
        original = get_config()
        with ConfigContext(log_level="ERROR") as cfg:
            assert cfg.log_level == "ERROR"
            assert get_config().log_level == "ERROR"
        # After exiting the context, config should be restored
        assert get_config() is original

    def test_set_config_visible_from_other_thread(self) -> None:
        """Config changes should be visible across threads."""
        new_cfg = self._make_valid_config(log_level="DEBUG")
        set_config(new_cfg)

        result: list[str] = []

        def reader() -> None:
            result.append(get_config().log_level)

        t = threading.Thread(target=reader)
        t.start()
        t.join()
        assert result == ["DEBUG"]


# ---------------------------------------------------------------------------
# 3. AF_UNIX looked up on wrong module (`os` instead of `socket`)
# ---------------------------------------------------------------------------


class TestSocketConnectorAFUnix:
    """Verify that connect_unix actually uses socket.AF_UNIX."""

    def test_connect_unix_uses_socket_module(self) -> None:
        """If socket.AF_UNIX exists, it should be used to create the socket.
        Previously this looked at os.AF_UNIX which is always None."""
        with patch("dapper.launcher.launcher_ipc.socket") as mock_socket_mod:
            mock_socket_mod.AF_UNIX = getattr(socket, "AF_UNIX", 1)
            mock_socket_mod.SOCK_STREAM = socket.SOCK_STREAM
            mock_sock = MagicMock()
            mock_socket_mod.socket.return_value = mock_sock

            connector = SocketConnector()
            result = connector.connect_unix("/tmp/test_sock")

            assert result is mock_sock
            mock_socket_mod.socket.assert_called_once_with(
                mock_socket_mod.AF_UNIX, mock_socket_mod.SOCK_STREAM
            )

    def test_connect_unix_returns_none_without_af_unix(self) -> None:
        """Without AF_UNIX on the socket module, should return None."""
        with patch("dapper.launcher.launcher_ipc.socket") as mock_socket_mod:
            # Remove AF_UNIX attribute
            del mock_socket_mod.AF_UNIX
            connector = SocketConnector()
            result = connector.connect_unix("/tmp/test_sock")
            assert result is None


# ---------------------------------------------------------------------------
# 4. Duplicate _get_runtime_completions call
# ---------------------------------------------------------------------------


class TestCompletionsNoDuplicateCall:
    """Verify that completions only calls _get_runtime_completions once
    on the fallback path (no frame)."""

    def test_fallback_completions_called_once(self) -> None:
        """Without a frame, _get_runtime_completions should be called exactly
        once, not twice (the copy-paste bug)."""
        ip = InProcessDebugger()
        call_count = 0
        original = ip._get_runtime_completions

        def counting_wrapper(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)

        ip._get_runtime_completions = counting_wrapper  # type: ignore[assignment]

        # Call completions without a frame (frame_id=None triggers fallback)
        result = ip.completions(
            text="pri",
            column=4,
            frame_id=None,
            line=1,
        )

        assert "targets" in result
        assert call_count == 1, f"_get_runtime_completions called {call_count} times, expected 1"


# ---------------------------------------------------------------------------
# 5. _handle_regular_breakpoint returns False on STOP → wrong stop reason
# ---------------------------------------------------------------------------


class TestHandleRegularBreakpointReturnValue:
    """Verify that _handle_regular_breakpoint returns True and emits a
    'breakpoint' stopped event when the breakpoint resolver says STOP."""

    def _make_test_file(self) -> str:
        """Create a real temp file so bdb.set_break succeeds."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1\ny = 2\nz = 3\nresult = x + y\nprint(z)\n")
            return f.name

    def test_returns_true_on_stop(self) -> None:
        """When the resolver returns STOP, the method should return True
        (meaning 'handled') and emit a stopped event with reason 'breakpoint'."""
        mock_send = MagicMock()
        dbg = DebuggerBDB(send_message=mock_send)

        test_file = self._make_test_file()
        try:
            dbg.set_break(test_file, 4)

            # Make the resolver return STOP
            dbg.breakpoint_resolver = MagicMock()
            dbg.breakpoint_resolver.resolve.return_value = ResolveResult(action=ResolveAction.STOP)

            # Mock process_commands and set_continue so we don't block
            dbg.process_commands = MagicMock()
            dbg.set_continue = MagicMock()

            frame = make_real_frame({"x": 1}, filename=test_file, lineno=4)

            result = dbg._handle_regular_breakpoint(test_file, 4, frame)

            # Should return True (handled)
            assert result is True

            # Should have emitted a stopped event with reason "breakpoint"
            mock_send.assert_any_call(
                "stopped",
                threadId=threading.get_ident(),
                reason="breakpoint",
                allThreadsStopped=True,
            )
        finally:
            Path(test_file).unlink(missing_ok=True)

    def test_returns_true_on_continue(self) -> None:
        """When the resolver returns CONTINUE, the method should also
        return True (handled — skipped due to condition)."""
        dbg = DebuggerBDB(send_message=MagicMock())

        test_file = self._make_test_file()
        try:
            dbg.set_break(test_file, 4)

            dbg.breakpoint_resolver = MagicMock()
            dbg.breakpoint_resolver.resolve.return_value = ResolveResult(
                action=ResolveAction.CONTINUE
            )
            dbg.set_continue = MagicMock()

            frame = make_real_frame({"x": 1}, filename=test_file, lineno=4)

            result = dbg._handle_regular_breakpoint(test_file, 4, frame)
            assert result is True
        finally:
            Path(test_file).unlink(missing_ok=True)

    def test_returns_false_when_no_breakpoint(self) -> None:
        """When no breakpoint exists at the given location, should return False."""
        dbg = DebuggerBDB(send_message=MagicMock())
        frame = make_real_frame({"x": 1}, filename="/test/regression.py", lineno=5)

        result = dbg._handle_regular_breakpoint("/test/regression.py", 5, frame)
        assert result is False


# ---------------------------------------------------------------------------
# 6. ExternalProcessBackend dispatch table called public methods → recursion
# ---------------------------------------------------------------------------


class TestExternalBackendDispatchNoRecursion:
    """Verify that _execute_command's dispatch table does NOT route through
    the public BaseBackend methods (which would cause infinite recursion
    via _execute_with_timeout → _execute_command)."""

    @pytest.mark.asyncio
    async def test_set_breakpoints_dispatch_uses_send_command(self) -> None:
        """The 'set_breakpoints' dispatch entry should call _send_command
        directly, not self.set_breakpoints."""
        mock_ipc = MagicMock()

        async def noop_send(*a: Any, **kw: Any) -> None:
            pass

        mock_ipc.send_message = noop_send
        loop = asyncio.get_event_loop()
        pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        lock = MagicMock()

        backend = ExternalProcessBackend(
            ipc=mock_ipc,
            loop=loop,
            get_process_state=lambda: (MagicMock(), False),
            pending_commands=pending,
            lock=lock,
            get_next_command_id=MagicMock(return_value=1),
        )

        # Spy on _send_command to verify it's called directly
        send_calls: list[dict[str, Any]] = []

        async def spy_send(command: dict[str, Any], **_kwargs: Any) -> None:
            send_calls.append(command)
            # Don't actually send — just record the call

        backend._send_command = spy_send  # type: ignore[assignment]

        result = await backend._execute_command(
            "set_breakpoints",
            {"path": "/test/file.py", "breakpoints": [{"line": 10}]},
        )

        # Should have called _send_command at least once
        assert len(send_calls) >= 1
        # The command sent should be the DAP-level setBreakpoints
        assert send_calls[0]["command"] == "setBreakpoints"

        # Result should contain breakpoints
        assert "breakpoints" in result

    @pytest.mark.asyncio
    async def test_continue_dispatch_uses_send_command(self) -> None:
        """The 'continue' dispatch entry should call _send_command directly."""
        mock_ipc = MagicMock()
        loop = asyncio.get_event_loop()
        pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        lock = MagicMock()

        backend = ExternalProcessBackend(
            ipc=mock_ipc,
            loop=loop,
            get_process_state=lambda: (MagicMock(), False),
            pending_commands=pending,
            lock=lock,
            get_next_command_id=MagicMock(return_value=1),
        )

        send_calls: list[dict[str, Any]] = []

        async def spy_send(command: dict[str, Any], **_kwargs: Any) -> None:
            send_calls.append(command)

        backend._send_command = spy_send  # type: ignore[assignment]

        result = await backend._execute_command("continue", {"thread_id": 1})

        assert len(send_calls) == 1
        assert send_calls[0]["command"] == "continue"
        assert result == {"allThreadsContinued": True}

    @pytest.mark.asyncio
    async def test_dispatch_map_reused_and_build_not_called(self) -> None:
        """Ensure dispatch map is created once and _build_dispatch_table is not used."""
        mock_ipc = MagicMock()
        loop = asyncio.get_event_loop()
        pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        lock = MagicMock()

        backend = ExternalProcessBackend(
            ipc=mock_ipc,
            loop=loop,
            get_process_state=lambda: (MagicMock(), False),
            pending_commands=pending,
            lock=lock,
            get_next_command_id=MagicMock(return_value=1),
        )

        # Ensure prebuilt dispatch_map exists
        assert hasattr(backend, "_dispatch_map")
        assert isinstance(backend._dispatch_map, dict)
        old_id = id(backend._dispatch_map)

        # Replace _build_dispatch_table with a sentinel that would fail if called
        def _bad_builder(_args: dict[str, Any]):
            raise AssertionError(
                "_build_dispatch_table should not be called when _dispatch_map is present"
            )

        backend._build_dispatch_table = _bad_builder  # type: ignore[assignment]

        # Call the same command twice and ensure dispatch_map is reused
        await backend._execute_command("set_breakpoints", {"path": "/x", "breakpoints": []})
        await backend._execute_command("set_breakpoints", {"path": "/x", "breakpoints": []})

        assert id(backend._dispatch_map) == old_id
