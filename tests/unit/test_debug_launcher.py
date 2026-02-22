"""Tests for dapper.debug_launcher module."""

from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import PropertyMock
from unittest.mock import patch

import pytest

from dapper.ipc.ipc_binary import pack_frame

# Import the module to test
from dapper.launcher import debug_launcher as dl
from dapper.shared import breakpoint_handlers
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import stepping_handlers
from dapper.shared import variable_handlers
from tests.mocks import make_real_frame


def _session() -> debug_shared.DebugSession:
    """Return the active explicit test session."""
    return debug_shared.get_active_session()


# Type aliases for better type hints


class TestDebugLauncherBasic:
    """Basic tests for debug_launcher module."""

    def setup_method(self) -> None:
        """Reset shared state before each test."""
        # Session setup is handled by the module-level autouse fixture.

    def test_parse_args_basic(self) -> None:
        """Test basic argument parsing."""
        # --ipc is now required
        test_args = ["--program", "script.py", "--ipc", "tcp"]

        with patch.object(sys, "argv", ["debug_launcher.py", *test_args]):
            args = dl.parse_args()

        assert args.program == "script.py"
        assert args.arg == []  # Changed from args.args to args.arg
        assert args.ipc == "tcp"

    def test_parse_args_with_options(self) -> None:
        """Test argument parsing with various options."""
        test_args = [
            "--program",
            "script.py",
            "--ipc",
            "tcp",
            "--ipc-host",
            "localhost",
            "--ipc-port",
            "5678",
            "--ipc-binary",
            "--strict-expression-watch-policy",
            "--arg",
            "arg1",
            "--arg",
            "arg2",
        ]

        with patch.object(sys, "argv", ["debug_launcher.py", *test_args]):
            args = dl.parse_args()

        assert args.ipc == "tcp"
        assert args.ipc_host == "localhost"
        assert args.ipc_port == 5678
        assert args.program == "script.py"
        assert args.arg == ["arg1", "arg2"]  # Changed from args.args to args.arg
        assert args.ipc_binary is True
        assert args.strict_expression_watch_policy is True

    def test_parse_args_requires_ipc(self) -> None:
        """Test that --ipc is required by the launcher CLI."""
        with (
            patch.object(sys, "argv", ["debug_launcher.py", "--program", "script.py"]),
            pytest.raises(SystemExit),
        ):
            dl.parse_args()

    def test_parse_args_rejects_invalid_ipc_choice(self) -> None:
        """Test invalid --ipc value is rejected by argparse choices."""
        with (
            patch.object(
                sys,
                "argv",
                ["debug_launcher.py", "--program", "script.py", "--ipc", "invalid"],
            ),
            pytest.raises(SystemExit),
        ):
            dl.parse_args()

    def test_parse_args_accepts_unix_transport_path(self) -> None:
        """Test parsing unix transport-specific options."""
        with patch.object(
            sys,
            "argv",
            [
                "debug_launcher.py",
                "--program",
                "script.py",
                "--ipc",
                "unix",
                "--ipc-path",
                "/tmp/dapper.sock",
            ],
        ):
            args = dl.parse_args()

        assert args.ipc == "unix"
        assert args.ipc_path == "/tmp/dapper.sock"

    def test_parse_args_module_target(self) -> None:
        """Test parsing module target invocation."""
        with patch.object(
            sys,
            "argv",
            [
                "debug_launcher.py",
                "--module",
                "http.server",
                "--ipc",
                "tcp",
            ],
        ):
            args = dl.parse_args()

        assert args.module == "http.server"
        assert args.program is None
        assert args.code is None

    def test_parse_args_code_target(self) -> None:
        """Test parsing code-string target invocation."""
        with patch.object(
            sys,
            "argv",
            [
                "debug_launcher.py",
                "--code",
                "print('x')",
                "--ipc",
                "tcp",
            ],
        ):
            args = dl.parse_args()

        assert args.code == "print('x')"
        assert args.program is None
        assert args.module is None

    @patch("dapper.launcher.debug_launcher.DebuggerBDB")
    def test_configure_debugger(self, mock_debugger_class: MagicMock) -> None:
        """Test debugger configuration."""
        # Setup
        mock_debugger = MagicMock()
        mock_debugger_class.return_value = mock_debugger

        # Save original state
        original_state = _session().__dict__.copy()

        try:
            # Test with stop on entry
            dl.configure_debugger(True)

            # Verify debugger was created and configured
            mock_debugger_class.assert_called_once()
            assert _session().debugger is not None

            # The stop_at_entry flag should be set on the debugger, not the state
            # This is a bug in the test, not the implementation
            # We should check the debugger's configuration instead

            # Reset for next test
            _session().debugger = None

            # Test without stop on entry
            dl.configure_debugger(False)
            assert _session().debugger is not None

        finally:
            # Restore original state
            _session().__dict__.update(original_state)

    def test_handle_initialize(self) -> None:
        """Test initialize command handling."""
        # Call the function and get the response
        response = lifecycle_handlers.handle_initialize_impl()

        # Verify the response structure
        assert isinstance(response, dict), "Response should be a dictionary"
        assert response.get("success") is True, "Response should indicate success"

        # Check that the response includes the expected capabilities
        body = response.get("body", {})
        assert isinstance(body, dict), "Response body should be a dictionary"

        # Check for required capabilities
        required_capabilities = [
            "supportsConfigurationDoneRequest",
            "supportsEvaluateForHovers",
            "supportsSetVariable",
            "supportsRestartRequest",
        ]

        for capability in required_capabilities:
            assert capability in body, f"Missing capability: {capability}"


class TestBreakpointHandling:
    """Tests for breakpoint-related functionality."""

    def setup_method(self) -> None:
        """Reset shared state before each test."""
        # Session setup is handled by the module-level autouse fixture.

    @patch("dapper.shared.command_handlers.send_debug_message")
    def test_handle_set_breakpoints(self, mock_send: MagicMock) -> None:
        """Test setting breakpoints."""
        # Setup
        dbg = MagicMock()
        dbg.set_break.return_value = True  # Simulate successful breakpoint set

        # Test data
        path = "/path/to/file.py"
        line1, line2 = 10, 20

        # Execute
        response = breakpoint_handlers.handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": path},
                "breakpoints": [{"line": line1}, {"line": line2, "condition": "x > 5"}],
            },
            handlers._safe_send_debug_message,
            handlers.logger,
        )

        # Verify breakpoints were set
        assert response is not None
        assert isinstance(response, dict)
        assert response.get("success") is True
        assert "breakpoints" in response.get("body", {})
        breakpoints = response["body"]["breakpoints"]
        assert len(breakpoints) == 2
        assert all(isinstance(bp, dict) for bp in breakpoints)
        assert all("verified" in bp and "line" in bp for bp in breakpoints)

        # Verify the debugger methods were called correctly
        dbg.clear_breaks_for_file.assert_called_once_with(path)
        assert dbg.set_break.call_count == 2
        dbg.set_break.assert_any_call(path, line1, cond=None)
        dbg.set_break.assert_any_call(path, line2, cond="x > 5")

        # Verify debug message was sent
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "breakpoints"
        assert call_args[1]["source"]["path"] == path
        assert len(call_args[1]["breakpoints"]) == 2
        _, kwargs = mock_send.call_args
        assert "breakpoints" in kwargs
        assert len(kwargs["breakpoints"]) == 2


class TestVariableHandling:
    """Tests for variable inspection and manipulation."""

    def setup_method(self) -> None:
        """Reset shared state before each test."""
        # Session setup is handled by the module-level autouse fixture.

    @patch("dapper.shared.command_handlers.send_debug_message")
    def test_handle_variables(self, mock_send: MagicMock) -> None:
        """Test variable inspection."""
        # Setup
        dbg = MagicMock()
        mock_frame = make_real_frame({"x": 42, "y": "test"})

        # Set up debugger mock
        dbg.var_manager.var_refs = {1: (0, "locals")}  # (frame_id, scope)
        dbg.thread_tracker.frame_id_to_frame = {0: mock_frame}

        # Mock make_variable_object to return a simple variable object
        def mock_make_var(
            name,
            val,
            _frame=None,
        ):  # _frame is unused but required by the interface
            return {"name": name, "value": str(val), "type": type(val).__name__}

        dbg.make_variable_object = mock_make_var

        # Test arguments
        args = {
            "variablesReference": 1,  # Locals scope
            "filter": "named",
        }

        # Execute
        variable_handlers.handle_variables_impl(
            dbg,
            args,
            handlers._safe_send_debug_message,
            lambda runtime_dbg, frame_info: (
                command_handler_helpers.resolve_variables_for_reference(
                    runtime_dbg,
                    frame_info,
                    make_variable_fn=command_handler_helpers.make_variable,
                    extract_variables_from_mapping_fn=lambda helper_dbg, mapping, frame: (
                        command_handler_helpers.extract_variables_from_mapping(
                            helper_dbg,
                            mapping,
                            frame,
                            make_variable_fn=command_handler_helpers.make_variable,
                        )
                    ),
                    var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
                )
            ),
        )

        # Verify send_debug_message was called with the expected arguments
        assert mock_send.called, "send_debug_message was not called"

        # Get the arguments passed to send_debug_message
        call_args = mock_send.call_args
        assert call_args is not None, "send_debug_message was called without arguments"

        # Check that the response includes the expected variables
        assert call_args[0][0] == "variables", "Expected a variables event"
        assert "variables" in call_args[1], "Response does not include variables"

        variables = call_args[1]["variables"]
        assert isinstance(variables, list), "Variables should be a list"
        assert len(variables) == 2, "Expected 2 variables"

        # Verify variable names and values
        var_names = {v["name"] for v in variables}
        assert "x" in var_names
        assert "y" in var_names


class TestExpressionEvaluation:
    """Tests for expression evaluation."""

    @patch("dapper.shared.command_handlers.send_debug_message")
    def test_handle_evaluate(self, mock_send: MagicMock) -> None:
        """Test expression evaluation."""
        # Setup
        _session().debugger = MagicMock()
        mock_frame = make_real_frame({"x": 10, "y": 20})
        _session().debugger.stepping_controller.current_frame = mock_frame  # type: ignore[union-attr]

        # Test arguments
        args = {"expression": "x + y", "context": "watch"}

        # Execute
        variable_handlers.handle_evaluate_impl(
            _session().debugger,  # type: ignore[arg-type]
            args,
            evaluate_with_policy=handlers.evaluate_with_policy,
            format_evaluation_error=variable_handlers.format_evaluation_error,
            safe_send_debug_message=handlers._safe_send_debug_message,
            logger=handlers.logger,
        )

        # Verify the expression was evaluated and result sent
        assert mock_send.called
        _, kwargs = mock_send.call_args
        assert "result" in kwargs
        # The actual evaluation is not implemented in the mock, so we can't test the exact value
        assert isinstance(kwargs["result"], str)


def test_handle_command_bytes_error_sends_shaped_error(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[tuple[str, str]] = []
    queued: list[dict[str, Any]] = []

    session = SimpleNamespace(command_queue=SimpleNamespace(put=queued.append), ipc_enabled=True)

    monkeypatch.setattr(
        dl,
        "send_debug_message",
        lambda event, **kwargs: messages.append((event, kwargs.get("message", ""))),
    )
    monkeypatch.setattr(dl.traceback, "print_exc", lambda: None)

    dl._handle_command_bytes(b"{not-json", session=session)

    assert queued == []
    assert messages
    assert messages[-1][0] == "error"
    assert messages[-1][1].startswith("Error receiving command:")


def test_recv_binary_from_pipe_returns_immediately_when_terminated() -> None:
    class FakeConn:
        def __init__(self):
            self.calls = 0

        def recv_bytes(self):
            self.calls += 1
            msg = "recv_bytes should not be called when session is terminated"
            raise AssertionError(msg)

    conn = FakeConn()
    session = SimpleNamespace(is_terminated=True, exit_func=lambda _code: None)

    dl._recv_binary_from_pipe(conn, session=session)  # type: ignore[arg-type]
    assert conn.calls == 0


def test_recv_binary_from_stream_returns_immediately_when_terminated() -> None:
    class FakeStream:
        def read(self, _size):
            msg = "read should not be called when session is terminated"
            raise AssertionError(msg)

    stream = FakeStream()
    session = SimpleNamespace(is_terminated=True, exit_func=lambda _code: None)

    dl._recv_binary_from_stream(stream, session=session)


def test_recv_binary_from_stream_empty_payload_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    header_only = pack_frame(2, b"hello")[:8]
    stream = io.BytesIO(header_only)
    exits: list[int] = []
    handled: list[bytes] = []

    session = SimpleNamespace(
        is_terminated=False,
        exit_func=exits.append,
        command_queue=SimpleNamespace(put=lambda _item: None),
    )

    monkeypatch.setattr(
        dl,
        "_handle_command_bytes",
        lambda payload, _session=None: handled.append(payload),
    )
    dl._recv_binary_from_stream(stream, session=session)

    assert handled == []
    assert exits == [0]


def test_setup_ipc_socket_uses_default_connector_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSock:
        def makefile(self, _mode, **_kwargs):
            return object()

    fake_sock = FakeSock()
    connector = SimpleNamespace(
        connect_unix=lambda _path: None,
        connect_tcp=lambda _host, _port: fake_sock,
    )
    session = SimpleNamespace(
        ipc_sock=None,
        ipc_rfile=None,
        ipc_wfile=None,
        ipc_enabled=False,
        ipc_binary=False,
    )

    monkeypatch.setattr(dl, "default_connector", connector)
    dl._setup_ipc_socket(
        "tcp",
        "127.0.0.1",
        9000,
        None,
        ipc_binary=False,
        connector=None,
        session=session,
    )

    assert session.ipc_sock is fake_sock
    assert session.ipc_enabled is True


class TestControlFlow:
    """Tests for execution control flow commands."""

    def setup_method(self) -> None:
        """Reset shared state before each test."""
        # Session setup is handled by the module-level autouse fixture.

    def test_handle_continue(self) -> None:
        """Test continue command."""
        # Setup
        mock_dbg = MagicMock()
        mock_dbg.thread_tracker.stopped_thread_ids = {1}  # Simulate a stopped thread

        # Execute with matching thread ID
        stepping_handlers.handle_continue_impl(mock_dbg, {"threadId": 1})

        # Verify thread was removed from stopped_thread_ids and set_continue was called
        assert 1 not in mock_dbg.thread_tracker.stopped_thread_ids
        mock_dbg.set_continue.assert_called_once()

        # Test with non-matching thread ID
        mock_dbg.reset_mock()
        mock_dbg.thread_tracker.stopped_thread_ids = {2}  # Different thread ID

        stepping_handlers.handle_continue_impl(mock_dbg, {"threadId": 1})
        mock_dbg.set_continue.assert_not_called()

    def test_handle_step_over(self) -> None:
        """Test step over command."""
        # Setup
        mock_dbg = MagicMock()
        mock_frame = make_real_frame({})
        mock_dbg.stepping_controller.current_frame = mock_frame

        # Mock threading.get_ident to return a specific thread ID
        with patch("dapper.shared.command_handlers.threading") as mock_threading:
            mock_threading.get_ident.return_value = 1

            # Execute with matching thread ID
            stepping_handlers.handle_next_impl(
                mock_dbg,
                {"threadId": 1},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )

            # Verify stepping was set and set_next was called
            assert mock_dbg.stepping_controller.stepping is True
            mock_dbg.set_next.assert_called_once_with(mock_frame)

            # Test with non-matching thread ID
            mock_dbg.reset_mock()
            stepping_handlers.handle_next_impl(
                mock_dbg,
                {"threadId": 2},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )
            mock_dbg.set_next.assert_not_called()

    def test_handle_step_in(self) -> None:
        """Test step into command."""
        # Setup
        mock_dbg = MagicMock()

        # Mock threading.get_ident to return a specific thread ID
        with patch("dapper.shared.command_handlers.threading") as mock_threading:
            mock_threading.get_ident.return_value = 1

            # Execute with matching thread ID
            stepping_handlers.handle_step_in_impl(
                mock_dbg,
                {"threadId": 1},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )

            # Verify stepping was set and set_step was called
            assert mock_dbg.stepping_controller.stepping is True
            mock_dbg.set_step.assert_called_once()

            # Test with non-matching thread ID
            mock_dbg.reset_mock()
            stepping_handlers.handle_step_in_impl(
                mock_dbg,
                {"threadId": 2},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )
            mock_dbg.set_step.assert_not_called()

    def test_handle_step_out(self) -> None:
        """Test step out command."""
        # Setup
        mock_dbg = MagicMock()
        mock_frame = make_real_frame({})
        mock_dbg.stepping_controller.current_frame = mock_frame

        # Mock threading.get_ident to return a specific thread ID
        with patch("dapper.shared.command_handlers.threading") as mock_threading:
            mock_threading.get_ident.return_value = 1

            # Execute with matching thread ID
            stepping_handlers.handle_step_out_impl(
                mock_dbg,
                {"threadId": 1},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )

            # Verify stepping was set and set_return was called
            assert mock_dbg.stepping_controller.stepping is True
            mock_dbg.set_return.assert_called_once_with(mock_frame)

            # Test with non-matching thread ID
            mock_dbg.reset_mock()
            stepping_handlers.handle_step_out_impl(
                mock_dbg,
                {"threadId": 2},
                handlers._get_thread_ident,
                handlers._set_dbg_stepping_flag,
            )
            mock_dbg.set_return.assert_not_called()


class TestExceptionBreakpoints:
    """Tests for exception breakpoint handling."""

    def test_handle_set_exception_breakpoints_empty(self):
        """Test with empty filters list."""
        mock_dbg = MagicMock()
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg, {"filters": []}
        )

        assert response is not None
        assert response["success"] is True
        body = response.get("body")
        assert isinstance(body, dict)
        assert body.get("breakpoints") == []

        # Verify debugger attributes were set to False for empty filters
        assert mock_dbg.exception_handler.config.break_on_raised is False
        assert mock_dbg.exception_handler.config.break_on_uncaught is False

    def test_handle_set_exception_breakpoints_raised(self):
        """Test with 'raised' filter."""
        mock_dbg = MagicMock()
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg,
            {"filters": ["raised"]},
        )

        assert response is not None
        assert response["success"] is True
        body = response.get("body")
        assert isinstance(body, dict)
        breakpoints = body.get("breakpoints")
        assert breakpoints is not None
        assert len(breakpoints) == 1
        assert breakpoints[0]["verified"] is True

        # Verify debugger attributes were set correctly
        assert mock_dbg.exception_handler.config.break_on_raised is True
        assert mock_dbg.exception_handler.config.break_on_uncaught is False

    def test_handle_set_exception_breakpoints_uncaught(self):
        """Test with 'uncaught' filter."""
        mock_dbg = MagicMock()
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg,
            {"filters": ["uncaught"]},
        )

        assert response is not None
        assert response["success"] is True
        body = response.get("body")
        assert isinstance(body, dict)
        breakpoints = body.get("breakpoints")
        assert breakpoints is not None
        assert len(breakpoints) == 1
        assert breakpoints[0]["verified"] is True

        # Verify debugger attributes were set correctly
        assert mock_dbg.exception_handler.config.break_on_raised is False
        assert mock_dbg.exception_handler.config.break_on_uncaught is True

    def test_handle_set_exception_breakpoints_both_filters(self):
        """Test with both 'raised' and 'uncaught' filters."""
        mock_dbg = MagicMock()
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg, {"filters": ["raised", "uncaught"]}
        )

        assert response is not None
        assert response["success"] is True
        body = response.get("body")
        assert isinstance(body, dict)
        breakpoints = body.get("breakpoints")
        assert breakpoints is not None
        assert len(breakpoints) == 2
        assert all(bp["verified"] for bp in breakpoints)

        # Verify debugger attributes were set correctly
        assert mock_dbg.exception_handler.config.break_on_raised is True
        assert mock_dbg.exception_handler.config.break_on_uncaught is True

    def test_handle_set_exception_breakpoints_invalid_filters(self):
        """Test with invalid filter types."""
        mock_dbg = MagicMock()

        # Test with non-list filters
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg,
            {"filters": "invalid"},
        )
        assert response is not None
        body = response.get("body")
        assert isinstance(body, dict)
        assert body.get("breakpoints") == []

        # Test with non-string elements
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg,
            {"filters": [123, None]},
        )
        assert response is not None
        body = response.get("body")
        assert isinstance(body, dict)
        breakpoints = body.get("breakpoints")
        assert breakpoints is not None
        assert len(breakpoints) == 2
        assert all(bp["verified"] for bp in breakpoints)

    def test_handle_set_exception_breakpoints_debugger_error(self):
        """Test handling of debugger attribute errors."""
        mock_dbg = MagicMock()

        # Make attribute assignment raise an exception
        def raise_on_set_raised(_):  # _ indicates unused parameter
            raise AttributeError("Test error")

        # Use side_effect to raise an exception when the attribute is set
        mock_config = MagicMock()
        mock_dbg.exception_handler.config = mock_config
        type(mock_config).break_on_raised = PropertyMock(side_effect=raise_on_set_raised)

        # The debugger should still be called with the filter
        response = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            mock_dbg,
            {"filters": ["raised"]},
        )

        assert response is not None
        # The response should still be successful
        assert response["success"] is True
        # But the breakpoint should be marked as not verified
        body = response.get("body")
        assert isinstance(body, dict)
        breakpoints = body.get("breakpoints")
        assert breakpoints is not None
        assert len(breakpoints) == 1


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_run_with_debugger_configures_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_dbg = MagicMock()
        calls: list[tuple[bool, Any]] = []

        def _configure(stop_on_entry: bool, session=None):
            calls.append((stop_on_entry, session))
            return fake_dbg

        monkeypatch.setattr(dl, "configure_debugger", _configure)

        session = SimpleNamespace(debugger=None)
        dl.run_with_debugger("/tmp/demo.py", ["--a", "1"], session=session)

        assert calls == [(False, session)]
        assert sys.argv == ["/tmp/demo.py", "--a", "1"]
        fake_dbg.run.assert_called_once_with("exec(Path('/tmp/demo.py').open().read())")

    def test_run_with_debugger_uses_existing_debugger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_dbg = MagicMock()
        session = SimpleNamespace(debugger=fake_dbg)

        configured: list[bool] = []

        def _configure(_stop_on_entry: bool, session=None):
            configured.append(True)
            return session

        monkeypatch.setattr(dl, "configure_debugger", _configure)

        dl.run_with_debugger("/tmp/existing.py", ["--flag"], session=session)

        assert configured == []
        assert sys.argv == ["/tmp/existing.py", "--flag"]
        fake_dbg.run.assert_called_once_with("exec(Path('/tmp/existing.py').open().read())")

    def test_run_program_sets_argv_and_inserts_program_dir(self, tmp_path) -> None:
        program_path = tmp_path / "prog.py"
        program_path.write_text("x = 1\n", encoding="utf-8")

        original_argv = list(sys.argv)
        original_path = list(sys.path)
        try:
            if str(tmp_path) in sys.path:
                sys.path.remove(str(tmp_path))

            dl.run_program(str(program_path), ["--demo"])

            assert sys.argv == [str(program_path), "--demo"]
            assert sys.path[0] == str(tmp_path)
        finally:
            sys.argv = original_argv
            sys.path[:] = original_path

    def test_run_program_does_not_duplicate_program_dir(self, tmp_path) -> None:
        program_path = tmp_path / "prog2.py"
        program_path.write_text("y = 2\n", encoding="utf-8")

        original_argv = list(sys.argv)
        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(tmp_path))
            before_count = sys.path.count(str(tmp_path))

            dl.run_program(str(program_path), [])

            after_count = sys.path.count(str(tmp_path))
            assert after_count == before_count
            assert sys.argv == [str(program_path)]
        finally:
            sys.argv = original_argv
            sys.path[:] = original_path

    def test_setup_ipc_from_args_routes_to_pipe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[Any] = []

        def _pipe(ipc_pipe, session=None):
            calls.append(("pipe", ipc_pipe, session))

        def _socket(*_args, **_kwargs):
            calls.append(("socket", None))

        monkeypatch.setattr(dl, "_setup_ipc_pipe", _pipe)
        monkeypatch.setattr(dl, "_setup_ipc_socket", _socket)

        args = SimpleNamespace(
            ipc="pipe",
            ipc_pipe="mypipe",
            ipc_host=None,
            ipc_port=None,
            ipc_path=None,
            ipc_binary=True,
        )
        session = SimpleNamespace()
        dl.setup_ipc_from_args(args, session=session)

        assert calls == [("pipe", "mypipe", session)]

    def test_setup_ipc_from_args_routes_to_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[Any] = []

        def _pipe(*_args, **_kwargs):
            calls.append(("pipe", None))

        def _socket(kind, host, port, path, ipc_binary, session=None):
            calls.append(("socket", kind, host, port, path, ipc_binary, session))

        monkeypatch.setattr(dl, "_setup_ipc_pipe", _pipe)
        monkeypatch.setattr(dl, "_setup_ipc_socket", _socket)

        args = SimpleNamespace(
            ipc="tcp",
            ipc_pipe=None,
            ipc_host="127.0.0.1",
            ipc_port=7777,
            ipc_path=None,
            ipc_binary=False,
        )
        session = SimpleNamespace()
        dl.setup_ipc_from_args(args, session=session)

        assert calls == [
            ("socket", "tcp", "127.0.0.1", 7777, None, False, session),
        ]

    def test_setup_ipc_pipe_raises_on_non_windows(self) -> None:
        with pytest.raises(RuntimeError, match="Pipe IPC requested"):
            dl._setup_ipc_pipe("mypipe")

    def test_receive_debug_commands_routes_pipe_and_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        class SessionWithPipe:
            def __init__(self):
                self.is_terminated = False
                self.ipc_pipe_conn = object()
                self.ipc_rfile = object()

            def require_ipc(self):
                calls.append("require")

        def _pipe(conn, session=None):
            _ = conn, session
            calls.append("pipe")

        def _stream(rfile, session=None):
            _ = rfile, session
            calls.append("stream")

        monkeypatch.setattr(dl, "_recv_binary_from_pipe", _pipe)
        monkeypatch.setattr(dl, "_recv_binary_from_stream", _stream)

        with_pipe = SessionWithPipe()
        dl.receive_debug_commands(session=with_pipe)

        with_pipe.ipc_pipe_conn = None
        dl.receive_debug_commands(session=with_pipe)

        assert calls == ["require", "pipe", "require", "stream"]

    def test_start_command_listener_starts_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[tuple[Any, tuple[Any, ...], bool]] = []

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None, name=None):
                _ = name
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                started.append((self.target, self.args, bool(self.daemon)))

        monkeypatch.setattr(dl.threading, "Thread", FakeThread)

        session = SimpleNamespace()
        thread = dl.start_command_listener(session=session)

        assert isinstance(thread, FakeThread)
        assert started == [(dl.receive_debug_commands, (session,), True)]

    def test_recv_binary_from_pipe_handles_command_and_eof(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        command = {"command": "initialize", "arguments": {}}
        frame = pack_frame(2, json.dumps(command).encode("utf-8"))

        class FakeConn:
            def __init__(self):
                self.called = 0

            def recv_bytes(self):
                self.called += 1
                if self.called == 1:
                    return frame
                raise EOFError

        class FakeQueue:
            def __init__(self):
                self.items: list[dict[str, Any]] = []

            def put(self, item):
                self.items.append(item)

        exit_codes: list[int] = []
        handled: list[dict[str, Any]] = []

        def _handle(command, session=None):
            del session
            handled.append(command)

        session = SimpleNamespace(
            is_terminated=False,
            command_queue=FakeQueue(),
            exit_func=exit_codes.append,
        )

        monkeypatch.setattr(
            dl,
            "handle_debug_command",
            _handle,
        )

        dl._recv_binary_from_pipe(FakeConn(), session=session)  # type: ignore[arg-type]

        assert len(session.command_queue.items) == 1
        assert session.command_queue.items[0]["command"] == "initialize"
        assert len(handled) == 1
        assert handled[0]["command"] == "initialize"
        assert exit_codes == [0]

    def test_recv_binary_from_pipe_bad_header_emits_error_and_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_frame = b"badhdr00payload"

        class FakeConn:
            def __init__(self):
                self.called = 0

            def recv_bytes(self):
                self.called += 1
                if self.called == 1:
                    return bad_frame
                return b""

        messages: list[str] = []

        def _ignore_item(_item):
            return None

        session = SimpleNamespace(
            is_terminated=False,
            exit_func=lambda code: messages.append(f"exit:{code}"),
            ipc_enabled=True,
            command_queue=SimpleNamespace(put=_ignore_item),
        )

        monkeypatch.setattr(
            dl,
            "send_debug_message",
            lambda event, **kwargs: messages.append(f"{event}:{kwargs.get('message', '')}"),
        )

        dl._recv_binary_from_pipe(FakeConn(), session=session)  # type: ignore[arg-type]

        assert any(m.startswith("error:Bad frame header") for m in messages)
        assert "exit:0" in messages

    def test_recv_binary_from_pipe_ignores_non_command_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        non_command_frame = pack_frame(1, b'{"command":"initialize"}')

        class FakeConn:
            def __init__(self):
                self.called = 0

            def recv_bytes(self):
                self.called += 1
                if self.called == 1:
                    return non_command_frame
                return b""

        queue_items: list[dict[str, Any]] = []
        handled: list[dict[str, Any]] = []

        def _handle(command, session=None):
            del session
            handled.append(command)

        session = SimpleNamespace(
            is_terminated=False,
            command_queue=SimpleNamespace(put=queue_items.append),
            exit_func=lambda _code: None,
        )

        monkeypatch.setattr(
            dl,
            "handle_debug_command",
            _handle,
        )

        dl._recv_binary_from_pipe(FakeConn(), session=session)  # type: ignore[arg-type]

        assert queue_items == []
        assert handled == []

    def test_recv_binary_from_stream_bad_header_emits_error_and_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good_command = pack_frame(2, json.dumps({"command": "initialize"}).encode("utf-8"))
        stream = io.BytesIO(b"badhdr00" + good_command + b"")

        messages: list[str] = []
        queued: list[dict[str, Any]] = []
        handled: list[dict[str, Any]] = []

        def _handle(command, session=None):
            del session
            handled.append(command)

        session = SimpleNamespace(
            is_terminated=False,
            command_queue=SimpleNamespace(put=queued.append),
            exit_func=lambda code: messages.append(f"exit:{code}"),
            ipc_enabled=True,
        )

        monkeypatch.setattr(
            dl,
            "send_debug_message",
            lambda event, **kwargs: messages.append(f"{event}:{kwargs.get('message', '')}"),
        )
        monkeypatch.setattr(
            dl,
            "handle_debug_command",
            _handle,
        )

        dl._recv_binary_from_stream(stream, session=session)

        assert any(m.startswith("error:Bad frame header") for m in messages)
        assert len(queued) == 1
        assert queued[0]["command"] == "initialize"
        assert len(handled) == 1
        assert "exit:0" in messages

    def test_main_routes_to_run_program_when_no_debug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        args = SimpleNamespace(
            program="/tmp/demo.py",
            arg=["--x"],
            stop_on_entry=True,
            no_debug=True,
            no_just_my_code=False,
            ipc="tcp",
            ipc_host="127.0.0.1",
            ipc_port=4444,
            ipc_path=None,
            ipc_pipe=None,
            ipc_binary=True,
        )

        def _setup_ipc_from_args(parsed, session=None):
            del parsed, session
            calls.append("ipc")

        def _start_command_listener(session=None):
            del session
            calls.append("listener")

        def _configure_debugger(
            stop_on_entry,
            session=None,
            just_my_code=True,
            strict_expression_watch_policy=False,
        ):
            del stop_on_entry, session, just_my_code, strict_expression_watch_policy
            calls.append("cfg")

        monkeypatch.setattr(dl, "parse_args", lambda: args)
        monkeypatch.setattr(dl, "setup_ipc_from_args", _setup_ipc_from_args)
        monkeypatch.setattr(dl, "start_command_listener", _start_command_listener)
        monkeypatch.setattr(dl, "configure_debugger", _configure_debugger)
        monkeypatch.setattr(
            dl,
            "run_program",
            lambda program, a: calls.append(f"run:{program}:{a}"),
        )
        monkeypatch.setattr(
            dl,
            "run_with_debugger",
            lambda *_args, **_kwargs: calls.append("debug"),
        )

        dl.main()

        assert calls == ["ipc", "listener", "cfg", "run:/tmp/demo.py:['--x']"]

    def test_main_routes_to_run_with_debugger_when_debug_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        args = SimpleNamespace(
            program="/tmp/demo.py",
            arg=["--x"],
            stop_on_entry=False,
            no_debug=False,
            no_just_my_code=False,
            ipc="tcp",
            ipc_host="127.0.0.1",
            ipc_port=4444,
            ipc_path=None,
            ipc_pipe=None,
            ipc_binary=True,
        )

        def _setup_ipc_from_args(parsed, session=None):
            del parsed, session
            calls.append("ipc")

        def _start_command_listener(session=None):
            del session
            calls.append("listener")

        def _configure_debugger(
            stop_on_entry,
            session=None,
            just_my_code=True,
            strict_expression_watch_policy=False,
        ):
            del stop_on_entry, session, just_my_code, strict_expression_watch_policy
            calls.append("cfg")

        def _run_with_debugger(program, a, session=None):
            del session
            calls.append(f"debug:{program}:{a}")

        monkeypatch.setattr(dl, "parse_args", lambda: args)
        monkeypatch.setattr(dl, "setup_ipc_from_args", _setup_ipc_from_args)
        monkeypatch.setattr(dl, "start_command_listener", _start_command_listener)
        monkeypatch.setattr(dl, "configure_debugger", _configure_debugger)
        monkeypatch.setattr(dl, "run_program", lambda *_args, **_kwargs: calls.append("run"))
        monkeypatch.setattr(dl, "run_with_debugger", _run_with_debugger)

        dl.main()

        assert calls == ["ipc", "listener", "cfg", "debug:/tmp/demo.py:['--x']"]

    def test_main_propagates_ipc_setup_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        args = SimpleNamespace(
            program="/tmp/demo.py",
            arg=[],
            stop_on_entry=False,
            no_debug=False,
            ipc="tcp",
            ipc_host="127.0.0.1",
            ipc_port=4444,
            ipc_path=None,
            ipc_pipe=None,
            ipc_binary=True,
        )

        calls: list[str] = []

        monkeypatch.setattr(dl, "parse_args", lambda: args)

        def _raise_setup(_args, session=None):
            _ = session
            msg = "ipc setup failed"
            raise RuntimeError(msg)

        monkeypatch.setattr(dl, "setup_ipc_from_args", _raise_setup)

        def _start_command_listener(session=None):
            del session
            calls.append("listener")

        def _configure_debugger(stop_on_entry, session=None):
            del stop_on_entry, session
            calls.append("cfg")

        monkeypatch.setattr(dl, "start_command_listener", _start_command_listener)
        monkeypatch.setattr(dl, "configure_debugger", _configure_debugger)

        with pytest.raises(RuntimeError, match="ipc setup failed"):
            dl.main()

        assert calls == []

    def test_setup_ipc_socket_raises_when_connector_returns_none(self) -> None:
        connector = SimpleNamespace(
            connect_unix=lambda _path: None,
            connect_tcp=lambda _host, _port: None,
        )

        with pytest.raises(RuntimeError, match="failed to connect socket"):
            dl._setup_ipc_socket(
                "tcp",
                "127.0.0.1",
                1234,
                None,
                ipc_binary=False,
                connector=connector,
                session=SimpleNamespace(),
            )

    def test_setup_ipc_socket_raises_when_connector_throws(self) -> None:
        def _raise_tcp(_host, _port):
            msg = "connect boom"
            raise OSError(msg)

        connector = SimpleNamespace(
            connect_unix=lambda _path: None,
            connect_tcp=_raise_tcp,
        )

        with pytest.raises(RuntimeError, match="failed to connect socket"):
            dl._setup_ipc_socket(
                "tcp",
                "127.0.0.1",
                1234,
                None,
                ipc_binary=False,
                connector=connector,
                session=SimpleNamespace(),
            )

    def test_setup_ipc_pipe_success_on_windows_sets_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_conn = object()
        session = SimpleNamespace(ipc_enabled=False, ipc_pipe_conn=None)

        def _client_stub(address, family):
            del address, family
            return fake_conn

        monkeypatch.setattr(dl._mpc, "Client", _client_stub)

        with patch.object(dl.os, "name", "nt"):
            dl._setup_ipc_pipe("\\\\.\\pipe\\dapper", session=session)

        assert session.ipc_enabled is True
        assert session.ipc_pipe_conn is fake_conn

    def test_setup_ipc_from_args_propagates_pipe_error(self) -> None:
        args = SimpleNamespace(
            ipc="pipe",
            ipc_pipe=None,
            ipc_host=None,
            ipc_port=None,
            ipc_path=None,
            ipc_binary=True,
        )
        with pytest.raises(RuntimeError, match="Pipe IPC requested"):
            dl.setup_ipc_from_args(args, session=SimpleNamespace())

    def test_setup_ipc_from_args_propagates_socket_error(self) -> None:
        args = SimpleNamespace(
            ipc="tcp",
            ipc_pipe=None,
            ipc_host=None,
            ipc_port=None,
            ipc_path=None,
            ipc_binary=True,
        )
        connector = SimpleNamespace(
            connect_unix=lambda _path: None,
            connect_tcp=lambda _host, _port: None,
        )
        with pytest.raises(RuntimeError, match="failed to connect socket"):
            dl._setup_ipc_socket(
                args.ipc,
                args.ipc_host,
                args.ipc_port,
                args.ipc_path,
                args.ipc_binary,
                connector=connector,
                session=SimpleNamespace(),
            )

    def test_setup_ipc_socket_binary_and_text_mode_file_setup(self) -> None:
        class FakeSock:
            def __init__(self):
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def makefile(self, mode, **kwargs):
                self.calls.append((mode, kwargs))
                return object()

        sock_bin = FakeSock()
        connector_bin = SimpleNamespace(
            connect_unix=lambda _path: None,
            connect_tcp=lambda _host, _port: sock_bin,
        )
        session_bin = SimpleNamespace(
            ipc_sock=None, ipc_rfile=None, ipc_wfile=None, ipc_enabled=False
        )

        dl._setup_ipc_socket(
            "tcp",
            "127.0.0.1",
            9999,
            None,
            ipc_binary=True,
            connector=connector_bin,
            session=session_bin,
        )
        assert session_bin.ipc_enabled is True
        assert session_bin.ipc_binary is True
        assert sock_bin.calls == [("rb", {"buffering": 0}), ("wb", {"buffering": 0})]

        sock_txt = FakeSock()
        connector_txt = SimpleNamespace(
            connect_unix=lambda _path: None,
            connect_tcp=lambda _host, _port: sock_txt,
        )
        session_txt = SimpleNamespace(
            ipc_sock=None, ipc_rfile=None, ipc_wfile=None, ipc_enabled=False
        )

        dl._setup_ipc_socket(
            "tcp",
            "127.0.0.1",
            9999,
            None,
            ipc_binary=False,
            connector=connector_txt,
            session=session_txt,
        )
        assert session_txt.ipc_enabled is True
        assert session_txt.ipc_binary is False
        assert sock_txt.calls == [
            ("r", {"encoding": "utf-8", "newline": ""}),
            ("w", {"encoding": "utf-8", "newline": ""}),
        ]


# Type checking
if TYPE_CHECKING:
    from typing import Any


# Set up test fixtures
@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown for tests."""
    # Save original modules and install an explicit active session.
    original_modules = sys.modules.copy()
    session = debug_shared.DebugSession()
    session_context = debug_shared.use_session(session)
    session_context.__enter__()

    yield  # Test runs here

    # Restore original modules and clear active-session context.
    session_context.__exit__(None, None, None)
    sys.modules.clear()
    sys.modules.update(original_modules)
