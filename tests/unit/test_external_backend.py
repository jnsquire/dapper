"""Tests for ExternalProcessBackend dispatch methods and supporting helpers."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.external_backend import _command_response_timeout_seconds

_UNSET = object()


def _make_backend(
    *,
    ipc: Any = None,
    process: Any = _UNSET,
    is_terminated: bool = False,
    pending_commands: dict | None = None,
    next_id: int = 1,
) -> ExternalProcessBackend:
    """Build a fully-constructed ExternalProcessBackend with sane defaults."""
    if ipc is None:
        ipc = MagicMock(send_message=AsyncMock(return_value=None))
    if process is _UNSET:
        process = MagicMock()
    if pending_commands is None:
        pending_commands = {}
    loop = asyncio.get_event_loop()
    return ExternalProcessBackend(
        ipc=ipc,
        loop=loop,
        get_process_state=lambda: (process, is_terminated),
        pending_commands=pending_commands,
        lock=threading.RLock(),
        get_next_command_id=MagicMock(return_value=next_id),
    )


def _make_backend_new() -> ExternalProcessBackend:
    """Bypass __init__ for unit-testing individual dispatch methods."""
    backend = ExternalProcessBackend.__new__(ExternalProcessBackend)
    backend._send_command = AsyncMock(return_value=None)
    return backend


class TestCommandResponseTimeoutSeconds:
    def test_returns_none_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", raising=False)
        assert _command_response_timeout_seconds() is None

    def test_returns_none_when_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "0")
        assert _command_response_timeout_seconds() is None

    def test_returns_none_when_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "-5")
        assert _command_response_timeout_seconds() is None

    def test_returns_none_on_non_numeric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "abc")
        assert _command_response_timeout_seconds() is None

    def test_returns_float_for_positive_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "30")
        result = _command_response_timeout_seconds()
        assert result == 30.0

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "  5.5  ")
        assert _command_response_timeout_seconds() == 5.5


class TestIsAvailable:
    def test_returns_true_when_process_alive(self) -> None:
        backend = _make_backend()
        assert backend.is_available() is True

    def test_returns_false_when_process_is_none(self) -> None:
        backend = _make_backend(process=None)
        assert backend.is_available() is False

    def test_returns_false_when_terminated(self) -> None:
        backend = _make_backend(is_terminated=True)
        assert backend.is_available() is False

    def test_returns_false_when_lifecycle_unavailable(self) -> None:
        backend = _make_backend()
        # Mock the lifecycle's is_available property to simulate an error state
        lifecycle_mock = MagicMock()
        lifecycle_mock.is_available = False
        backend._lifecycle = lifecycle_mock  # type: ignore[assignment]
        assert backend.is_available() is False


class TestExtractBody:
    def test_returns_default_for_none_response(self) -> None:
        backend = _make_backend_new()
        default = {"x": 1}
        assert backend._extract_body(None, default) is default

    def test_returns_default_when_no_body_key(self) -> None:
        backend = _make_backend_new()
        default = {"x": 1}
        assert backend._extract_body({"other": 2}, default) is default

    def test_returns_body_when_present(self) -> None:
        backend = _make_backend_new()
        result = backend._extract_body({"body": {"a": 1}}, {})
        assert result == {"a": 1}


class TestCleanup:
    def test_cleanup_ipc_calls_ipc_cleanup(self) -> None:
        ipc = MagicMock()
        backend = _make_backend(ipc=ipc)
        backend._cleanup_ipc()
        ipc.cleanup.assert_called_once()

    def test_cleanup_ipc_swallows_exceptions(self) -> None:
        ipc = MagicMock()
        ipc.cleanup.side_effect = RuntimeError("broken")
        backend = _make_backend(ipc=ipc)
        backend._cleanup_ipc()  # must not raise

    def test_cleanup_commands_cancels_pending(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            fut: asyncio.Future[dict[str, Any]] = loop.create_future()
            pending: dict[int, asyncio.Future[dict[str, Any]]] = {1: fut}
            backend = _make_backend(pending_commands=pending)
            backend._cleanup_commands()
            assert pending == {}
            assert fut.cancelled()
        finally:
            loop.close()

    def test_cleanup_commands_skips_already_done_futures(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            fut: asyncio.Future[dict[str, Any]] = loop.create_future()
            fut.set_result({})
            pending: dict[int, asyncio.Future[dict[str, Any]]] = {1: fut}
            backend = _make_backend(pending_commands=pending)
            backend._cleanup_commands()
            assert pending == {}
        finally:
            loop.close()


class TestBuildDispatchTable:
    def test_contains_all_expected_commands(self) -> None:
        backend = _make_backend()
        table = backend._build_dispatch_table({})
        for name in [
            "set_breakpoints",
            "continue",
            "next",
            "step_in",
            "step_out",
            "pause",
            "evaluate",
            "hot_reload",
        ]:
            assert name in table

    @pytest.mark.asyncio
    async def test_wraps_handler_as_zero_arg_callable(self) -> None:
        backend = _make_backend()
        captured: list[dict] = []

        async def _fake_dispatch(args: dict[str, Any]):
            captured.append(args)
            return {}

        backend._dispatch_map["evaluate"] = _fake_dispatch  # type: ignore[assignment]
        table = backend._build_dispatch_table({"expr": "1"})
        await table["evaluate"]()
        assert captured == [{"expr": "1"}]


class TestDispatchSetBreakpoints:
    @pytest.mark.asyncio
    async def test_sends_correct_command_shape(self) -> None:
        backend = _make_backend_new()
        bps = [{"line": 10, "condition": "x > 0"}, {"line": 20}]
        await backend._dispatch_set_breakpoints({"path": "/a/b.py", "breakpoints": bps})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "setBreakpoints"
        assert cmd["arguments"]["source"]["path"] == "/a/b.py"
        assert len(cmd["arguments"]["breakpoints"]) == 2

    @pytest.mark.asyncio
    async def test_returns_verified_breakpoints(self) -> None:
        backend = _make_backend_new()
        bps = [{"line": 5}, {"line": 15}]
        result = await backend._dispatch_set_breakpoints({"path": "/x.py", "breakpoints": bps})
        assert len(result["breakpoints"]) == 2
        assert all(bp["verified"] is True for bp in result["breakpoints"])
        assert result["breakpoints"][0].get("line") == 5
        assert result["breakpoints"][1].get("line") == 15


class TestDispatchSetFunctionBreakpoints:
    @pytest.mark.asyncio
    async def test_sends_correct_command(self) -> None:
        backend = _make_backend_new()
        bps = [{"name": "my_func"}]
        await backend._dispatch_set_function_breakpoints({"breakpoints": bps})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "setFunctionBreakpoints"
        assert cmd["arguments"]["breakpoints"] == [{"name": "my_func"}]

    @pytest.mark.asyncio
    async def test_returns_verified_true_by_default(self) -> None:
        backend = _make_backend_new()
        bps = [{"name": "func_a"}, {"name": "func_b", "verified": False}]
        result = await backend._dispatch_set_function_breakpoints({"breakpoints": bps})
        assert result["breakpoints"][0]["verified"] is True
        assert result["breakpoints"][1]["verified"] is False


class TestDispatchSetExceptionBreakpoints:
    @pytest.mark.asyncio
    async def test_sends_filters_only(self) -> None:
        backend = _make_backend_new()
        args = {"filters": ["raised", "uncaught"]}
        await backend._dispatch_set_exception_breakpoints(args)
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "setExceptionBreakpoints"
        assert cmd["arguments"]["filters"] == ["raised", "uncaught"]
        assert "filterOptions" not in cmd["arguments"]
        assert "exceptionOptions" not in cmd["arguments"]

    @pytest.mark.asyncio
    async def test_includes_filter_options_when_present(self) -> None:
        backend = _make_backend_new()
        fo = [{"filterId": "raised"}]
        args = {"filters": [], "filter_options": fo}
        await backend._dispatch_set_exception_breakpoints(args)
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["filterOptions"] == fo

    @pytest.mark.asyncio
    async def test_includes_exception_options_when_present(self) -> None:
        backend = _make_backend_new()
        eo = [{"path": [{"names": ["Exception"]}]}]
        args = {"filters": [], "exception_options": eo}
        await backend._dispatch_set_exception_breakpoints(args)
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["exceptionOptions"] == eo

    @pytest.mark.asyncio
    async def test_returns_verified_breakpoints_per_filter(self) -> None:
        backend = _make_backend_new()
        result = await backend._dispatch_set_exception_breakpoints({"filters": ["a", "b", "c"]})
        assert len(result["breakpoints"]) == 3
        assert all(bp["verified"] is True for bp in result["breakpoints"])


# ---------------------------------------------------------------------------
# _dispatch_next / step_in / step_out
# ---------------------------------------------------------------------------


class TestDispatchStepCommands:
    @pytest.mark.asyncio
    async def test_next_default_granularity_not_forwarded(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_next({"thread_id": 2, "granularity": "line"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "next"
        assert "granularity" not in cmd["arguments"]

    @pytest.mark.asyncio
    async def test_next_non_default_granularity_forwarded(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_next({"thread_id": 1, "granularity": "instruction"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["granularity"] == "instruction"

    @pytest.mark.asyncio
    async def test_next_returns_empty_body(self) -> None:
        backend = _make_backend_new()
        result = await backend._dispatch_next({"thread_id": 1})
        assert result == {}

    @pytest.mark.asyncio
    async def test_step_in_non_default_granularity(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_step_in({"thread_id": 1, "granularity": "statement"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "stepIn"
        assert cmd["arguments"]["granularity"] == "statement"

    @pytest.mark.asyncio
    async def test_step_out_sends_step_out_command(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_step_out({"thread_id": 3})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "stepOut"
        assert cmd["arguments"]["threadId"] == 3


# ---------------------------------------------------------------------------
# _dispatch_pause
# ---------------------------------------------------------------------------


class TestDispatchPause:
    @pytest.mark.asyncio
    async def test_sends_pause_and_returns_sent_true(self) -> None:
        backend = _make_backend_new()
        result = await backend._dispatch_pause({"thread_id": 5})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "pause"
        assert cmd["arguments"]["threadId"] == 5
        assert result["sent"] is True


# ---------------------------------------------------------------------------
# _dispatch_stack_trace
# ---------------------------------------------------------------------------


class TestDispatchStackTrace:
    @pytest.mark.asyncio
    async def test_sends_stack_trace_command(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": {"stackFrames": [{"id": 1}], "totalFrames": 1}}
        )
        result = await backend._dispatch_stack_trace({"thread_id": 2})
        cmd = backend._send_command.call_args[0][0]
        assert cmd["command"] == "stackTrace"
        assert cmd["arguments"]["threadId"] == 2
        assert result.get("totalFrames") == 1

    @pytest.mark.asyncio
    async def test_returns_default_on_none_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_stack_trace({"thread_id": 1})
        assert result["stackFrames"] == []
        assert result.get("totalFrames") == 0

    @pytest.mark.asyncio
    async def test_forwards_start_frame_and_levels(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_stack_trace({"thread_id": 1, "start_frame": 5, "levels": 10})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["startFrame"] == 5
        assert cmd["arguments"]["levels"] == 10


# ---------------------------------------------------------------------------
# _dispatch_variables
# ---------------------------------------------------------------------------


class TestDispatchVariables:
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_none_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_variables({"variables_reference": 1})
        assert result["variables"] == []

    @pytest.mark.asyncio
    async def test_returns_variables_from_body(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": {"variables": [{"name": "x", "value": "1"}]}}
        )
        result = await backend._dispatch_variables({"variables_reference": 5})
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "x"

    @pytest.mark.asyncio
    async def test_filter_type_included_when_set(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_variables({"variables_reference": 1, "filter_type": "named"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["filter"] == "named"

    @pytest.mark.asyncio
    async def test_start_and_count_included_when_positive(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_variables({"variables_reference": 1, "start": 3, "count": 10})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["start"] == 3
        assert cmd["arguments"]["count"] == 10

    @pytest.mark.asyncio
    async def test_start_and_count_omitted_when_zero(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_variables({"variables_reference": 1, "start": 0, "count": 0})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert "start" not in cmd["arguments"]
        assert "count" not in cmd["arguments"]


# ---------------------------------------------------------------------------
# _dispatch_set_variable
# ---------------------------------------------------------------------------


class TestDispatchSetVariable:
    @pytest.mark.asyncio
    async def test_sends_correct_command(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_set_variable({"var_ref": 7, "name": "x", "value": "42"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "setVariable"
        assert cmd["arguments"]["name"] == "x"
        assert cmd["arguments"]["value"] == "42"
        assert cmd["arguments"]["variablesReference"] == 7

    @pytest.mark.asyncio
    async def test_returns_body_from_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": {"value": "99", "type": "int", "variablesReference": 0}}
        )
        result = await backend._dispatch_set_variable({"var_ref": 1, "name": "y", "value": "99"})
        assert result["value"] == "99"
        assert result.get("type") == "int"

    @pytest.mark.asyncio
    async def test_falls_back_to_default_on_none_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_set_variable({"var_ref": 1, "name": "z", "value": "abc"})
        assert result["value"] == "abc"


# ---------------------------------------------------------------------------
# _dispatch_set_expression
# ---------------------------------------------------------------------------


class TestDispatchSetExpression:
    @pytest.mark.asyncio
    async def test_sends_correct_command_with_frame_id(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_set_expression({"expression": "x", "value": "5", "frame_id": 3})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "setExpression"
        assert cmd["arguments"]["expression"] == "x"
        assert cmd["arguments"]["frameId"] == 3

    @pytest.mark.asyncio
    async def test_falls_back_to_default_on_none_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_set_expression(
            {"expression": "y", "value": "99", "frame_id": None}
        )
        assert result["value"] == "99"


# ---------------------------------------------------------------------------
# _dispatch_evaluate
# ---------------------------------------------------------------------------


class TestDispatchEvaluate:
    @pytest.mark.asyncio
    async def test_sends_evaluate_command(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_evaluate({"expression": "1+1", "frame_id": 2, "context": "repl"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "evaluate"
        assert cmd["arguments"]["expression"] == "1+1"
        assert cmd["arguments"]["context"] == "repl"

    @pytest.mark.asyncio
    async def test_default_context_is_hover(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_evaluate({"expression": "x"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["context"] == "hover"

    @pytest.mark.asyncio
    async def test_returns_placeholder_on_no_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_evaluate({"expression": "foo"})
        assert "foo" in result.get("result", "")
        assert result.get("variablesReference") == 0

    @pytest.mark.asyncio
    async def test_returns_body_from_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": {"result": "42", "type": "int", "variablesReference": 0}}
        )
        result = await backend._dispatch_evaluate({"expression": "21+21"})
        assert result.get("result") == "42"


# ---------------------------------------------------------------------------
# _dispatch_completions
# ---------------------------------------------------------------------------


class TestDispatchCompletions:
    @pytest.mark.asyncio
    async def test_sends_completions_command(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_completions({"text": "os.", "column": 3})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "completions"
        assert cmd["arguments"]["text"] == "os."
        assert cmd["arguments"]["column"] == 3

    @pytest.mark.asyncio
    async def test_returns_empty_targets_on_no_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_completions({"text": "x", "column": 1})
        assert result["targets"] == []

    @pytest.mark.asyncio
    async def test_returns_targets_from_response_body(self) -> None:
        backend = _make_backend_new()
        targets = [{"label": "path"}, {"label": "getcwd"}]
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": {"targets": targets}}
        )
        result = await backend._dispatch_completions({"text": "os.", "column": 3})
        assert result["targets"] == targets


# ---------------------------------------------------------------------------
# _dispatch_exception_info
# ---------------------------------------------------------------------------


class TestDispatchExceptionInfo:
    @pytest.mark.asyncio
    async def test_sends_exception_info_command(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_exception_info({"thread_id": 9})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "exceptionInfo"
        assert cmd["arguments"]["threadId"] == 9

    @pytest.mark.asyncio
    async def test_returns_body_from_response(self) -> None:
        backend = _make_backend_new()
        body = {"exceptionId": "ValueError", "description": "bad", "breakMode": "always"}
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"body": body}
        )
        result = await backend._dispatch_exception_info({"thread_id": 1})
        assert result.get("exceptionId") == "ValueError"

    @pytest.mark.asyncio
    async def test_returns_empty_body_on_no_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_exception_info({"thread_id": 1})
        # ExceptionInfoResponseBody() should not raise and be dict-like
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _dispatch_configuration_done / _dispatch_terminate
# ---------------------------------------------------------------------------


class TestDispatchConfigurationDoneAndTerminate:
    @pytest.mark.asyncio
    async def test_configuration_done_sends_command(self) -> None:
        backend = _make_backend_new()
        result = await backend._dispatch_configuration_done({})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "configurationDone"
        assert result == {}

    @pytest.mark.asyncio
    async def test_terminate_sends_command(self) -> None:
        backend = _make_backend_new()
        result = await backend._dispatch_terminate({})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["command"] == "terminate"
        assert result == {}


# ---------------------------------------------------------------------------
# _dispatch_hot_reload
# ---------------------------------------------------------------------------


class TestDispatchHotReload:
    @pytest.mark.asyncio
    async def test_sends_hot_reload_command_with_path_and_options(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "success": True,
                "body": {
                    "reloadedModule": "mymod",
                    "reboundFrames": 1,
                    "updatedFrameCodes": 2,
                    "patchedInstances": 0,
                    "warnings": [],
                },
            }
        )
        result = await backend._dispatch_hot_reload(
            {"path": "/a/b.py", "options": {"invalidatePycache": True}}
        )
        cmd = backend._send_command.call_args[0][0]
        assert cmd["command"] == "hotReload"
        assert cmd["arguments"]["path"] == "/a/b.py"
        assert result.get("reloadedModule") == "mymod"
        assert result.get("reboundFrames") == 1

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_failure_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"success": False, "message": "reload failed"}
        )
        with pytest.raises(RuntimeError, match="reload failed"):
            await backend._dispatch_hot_reload({})

    @pytest.mark.asyncio
    async def test_raises_generic_message_when_no_message_field(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(  # type: ignore[method-assign]
            return_value={"success": False}
        )
        with pytest.raises(RuntimeError, match="hotReload failed"):
            await backend._dispatch_hot_reload({})

    @pytest.mark.asyncio
    async def test_returns_default_body_on_none_response(self) -> None:
        backend = _make_backend_new()
        backend._send_command = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await backend._dispatch_hot_reload({})
        assert result.get("reloadedModule") == "<unknown>"
        assert result.get("reboundFrames") == 0
        assert result.get("warnings") == []

    @pytest.mark.asyncio
    async def test_defaults_path_and_options_when_absent(self) -> None:
        backend = _make_backend_new()
        await backend._dispatch_hot_reload({})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["path"] == ""
        assert cmd["arguments"]["options"] == {}


# ---------------------------------------------------------------------------
# _execute_command
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_raises_when_not_available(self) -> None:
        backend = _make_backend(process=None)
        with pytest.raises(RuntimeError, match="not available"):
            await backend._execute_command("evaluate", {"expression": "1"})


# ---------------------------------------------------------------------------
# _send_command - timeout path
# ---------------------------------------------------------------------------


class TestSendCommandTimeout:
    @pytest.mark.asyncio
    async def test_times_out_and_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "0.05")
        pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        backend = _make_backend(
            ipc=MagicMock(send_message=AsyncMock(return_value=None)),
            pending_commands=pending,
        )
        # Future never resolves → timeout fires
        result = await backend._send_command({"command": "ping"}, expect_response=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_error_cleans_up_pending_entry(self) -> None:
        ipc = MagicMock()
        ipc.send_message = AsyncMock(side_effect=OSError("broken pipe"))
        pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        backend = _make_backend(ipc=ipc, pending_commands=pending, next_id=42)
        result = await backend._send_command({"command": "ping"}, expect_response=True)
        assert result is None
        assert 42 not in pending


# ---------------------------------------------------------------------------
# initialize / launch / attach
# ---------------------------------------------------------------------------


class TestLifecycleMethods:
    @pytest.mark.asyncio
    async def test_initialize_marks_backend_ready(self) -> None:
        backend = _make_backend()
        await backend.initialize()
        assert backend._lifecycle.is_available

    @pytest.mark.asyncio
    async def test_initialize_raises_when_not_available(self) -> None:
        backend = _make_backend(process=None)
        with pytest.raises(RuntimeError, match="not available"):
            await backend.initialize()

    @pytest.mark.asyncio
    async def test_launch_calls_initialize(self) -> None:
        backend = _make_backend()
        called = []
        original_init = backend.initialize

        async def _spy():
            called.append(True)
            await original_init()

        backend.initialize = _spy  # type: ignore[method-assign]
        await backend.launch(MagicMock())
        assert called

    @pytest.mark.asyncio
    async def test_attach_calls_initialize(self) -> None:
        backend = _make_backend()
        called = []
        original_init = backend.initialize

        async def _spy():
            called.append(True)
            await original_init()

        backend.initialize = _spy  # type: ignore[method-assign]
        await backend.attach(MagicMock())
        assert called
