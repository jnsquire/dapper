"""Tests for dapper/errors/error_patterns.py."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from dapper.errors.dapper_errors import BackendError
from dapper.errors.dapper_errors import ConfigurationError
from dapper.errors.dapper_errors import DapperError
from dapper.errors.dapper_errors import DapperTimeoutError
from dapper.errors.dapper_errors import DebuggerError
from dapper.errors.dapper_errors import IPCError
from dapper.errors.dapper_errors import ProtocolError
from dapper.errors.error_patterns import ErrorContext
from dapper.errors.error_patterns import _classify_adapter_error
from dapper.errors.error_patterns import _classify_backend_error
from dapper.errors.error_patterns import async_handle_adapter_errors
from dapper.errors.error_patterns import async_handle_backend_errors
from dapper.errors.error_patterns import async_handle_debugger_errors
from dapper.errors.error_patterns import handle_adapter_errors
from dapper.errors.error_patterns import handle_backend_errors
from dapper.errors.error_patterns import handle_debugger_errors
from dapper.errors.error_patterns import handle_protocol_errors

# ---------------------------------------------------------------------------
# _classify_adapter_error
# ---------------------------------------------------------------------------


class TestClassifyAdapterError:
    def test_connection_error_becomes_ipc_error(self) -> None:
        e = ConnectionError("broken pipe")
        result = _classify_adapter_error(e, operation="send")
        assert isinstance(result, IPCError)
        assert "send" in str(result)

    def test_broken_pipe_becomes_ipc_error(self) -> None:
        e = BrokenPipeError("pipe closed")
        result = _classify_adapter_error(e, operation="recv")
        assert isinstance(result, IPCError)

    def test_eof_error_becomes_ipc_error(self) -> None:
        e = EOFError("eof")
        result = _classify_adapter_error(e, operation="read")
        assert isinstance(result, IPCError)

    def test_timeout_error_becomes_dapper_timeout_error(self) -> None:
        e = TimeoutError("timed out")
        result = _classify_adapter_error(e, operation="connect")
        assert isinstance(result, DapperTimeoutError)

    def test_generic_error_becomes_dapper_error(self) -> None:
        e = RuntimeError("unexpected")
        result = _classify_adapter_error(e, operation="do_something")
        assert isinstance(result, DapperError)
        assert result.details.get("operation") == "do_something"


# ---------------------------------------------------------------------------
# _classify_backend_error
# ---------------------------------------------------------------------------


class TestClassifyBackendError:
    def test_timeout_error_becomes_dapper_timeout_error(self) -> None:
        e = TimeoutError("backend timeout")
        result = _classify_backend_error(e, operation="launch")
        assert isinstance(result, DapperTimeoutError)

    def test_generic_error_becomes_backend_error(self) -> None:
        e = ValueError("bad value")
        result = _classify_backend_error(e, operation="attach")
        assert isinstance(result, BackendError)
        assert result.details.get("operation") == "attach"


# ---------------------------------------------------------------------------
# handle_adapter_errors (sync decorator)
# ---------------------------------------------------------------------------


class TestHandleAdapterErrors:
    def test_return_value_preserved_on_success(self) -> None:
        @handle_adapter_errors("op")
        def fn() -> int:
            return 42

        assert fn() == 42

    def test_exception_swallowed_returns_none_by_default(self) -> None:
        @handle_adapter_errors("op")
        def fn() -> None:
            raise RuntimeError("boom")

        assert fn() is None

    def test_reraise_wraps_and_raises(self) -> None:
        @handle_adapter_errors("op", reraise=True)
        def fn() -> None:
            raise RuntimeError("boom")

        with pytest.raises(DapperError):
            fn()

    def test_configuration_error_reraised_when_reraise(self) -> None:
        @handle_adapter_errors("op", reraise=True)
        def fn() -> None:
            raise ConfigurationError("bad cfg")

        with pytest.raises(ConfigurationError):
            fn()

    def test_ipc_error_reraised_when_reraise(self) -> None:
        @handle_adapter_errors("op", reraise=True)
        def fn() -> None:
            raise IPCError("ipc fail")

        with pytest.raises(IPCError):
            fn()

    def test_protocol_error_reraised_when_reraise(self) -> None:
        @handle_adapter_errors("op", reraise=True)
        def fn() -> None:
            raise ProtocolError("proto fail")

        with pytest.raises(ProtocolError):
            fn()

    def test_operation_defaults_to_func_name(self, caplog: Any) -> None:
        @handle_adapter_errors()
        def my_function() -> None:
            raise RuntimeError("err")

        with caplog.at_level(logging.ERROR):
            my_function()

        assert "my_function" in caplog.text

    def test_custom_log_level(self, caplog: Any) -> None:
        @handle_adapter_errors("op", log_level=logging.DEBUG)
        def fn() -> None:
            raise RuntimeError("dbg")

        with caplog.at_level(logging.DEBUG):
            fn()

        assert "dbg" in caplog.text


# ---------------------------------------------------------------------------
# handle_backend_errors (sync decorator)
# ---------------------------------------------------------------------------


class TestHandleBackendErrors:
    def test_return_value_preserved(self) -> None:
        @handle_backend_errors("inprocess")
        def fn() -> str:
            return "ok"

        assert fn() == "ok"

    def test_exception_swallowed_returns_none(self) -> None:
        @handle_backend_errors("inprocess")
        def fn() -> None:
            raise RuntimeError("crash")

        assert fn() is None

    def test_reraise_wraps_and_raises(self) -> None:
        @handle_backend_errors("inprocess", reraise=True)
        def fn() -> None:
            raise RuntimeError("crash")

        with pytest.raises(BackendError):
            fn()

    def test_backend_error_passthrough_when_reraise(self) -> None:
        @handle_backend_errors("inprocess", reraise=True)
        def fn() -> None:
            raise BackendError("already backend")

        with pytest.raises(BackendError):
            fn()

    def test_timeout_error_passthrough_when_reraise(self) -> None:
        @handle_backend_errors("inprocess", reraise=True)
        def fn() -> None:
            raise DapperTimeoutError("timed out", operation="launch")

        with pytest.raises(DapperTimeoutError):
            fn()

    def test_backend_type_attached_to_wrapped_error(self) -> None:
        @handle_backend_errors("mybackend", reraise=True)
        def fn() -> None:
            raise RuntimeError("crash")

        with pytest.raises(BackendError) as exc_info:
            fn()

        err = exc_info.value
        assert err.details.get("backend_type") == "mybackend"


# ---------------------------------------------------------------------------
# handle_debugger_errors (sync decorator)
# ---------------------------------------------------------------------------


class TestHandleDebuggerErrors:
    def test_success_passthrough(self) -> None:
        @handle_debugger_errors("step")
        def fn() -> int:
            return 7

        assert fn() == 7

    def test_exception_swallowed(self) -> None:
        @handle_debugger_errors("step")
        def fn() -> None:
            raise RuntimeError("step failed")

        assert fn() is None

    def test_reraise_wraps_as_debugger_error(self) -> None:
        @handle_debugger_errors("step", reraise=True)
        def fn() -> None:
            raise RuntimeError("step failed")

        with pytest.raises(DebuggerError):
            fn()

    def test_thread_id_in_error(self) -> None:
        @handle_debugger_errors("step", thread_id=5, reraise=True)
        def fn() -> None:
            raise RuntimeError("err")

        with pytest.raises(DebuggerError) as exc_info:
            fn()

        assert exc_info.value.thread_id == 5


# ---------------------------------------------------------------------------
# handle_protocol_errors (sync decorator)
# ---------------------------------------------------------------------------


class TestHandleProtocolErrors:
    def test_success_passthrough(self) -> None:
        @handle_protocol_errors("next")
        def fn() -> str:
            return "done"

        assert fn() == "done"

    def test_exception_swallowed(self) -> None:
        @handle_protocol_errors("continue")
        def fn() -> None:
            raise RuntimeError("proto error")

        assert fn() is None

    def test_reraise_wraps_as_protocol_error(self) -> None:
        @handle_protocol_errors("continue", reraise=True)
        def fn() -> None:
            raise RuntimeError("proto error")

        with pytest.raises(ProtocolError):
            fn()

    def test_command_and_sequence_stored_on_error(self) -> None:
        @handle_protocol_errors("myCmd", sequence=99, reraise=True)
        def fn() -> None:
            raise RuntimeError("err")

        with pytest.raises(ProtocolError) as exc_info:
            fn()

        err = exc_info.value
        assert err.command == "myCmd"
        assert err.sequence == 99


# ---------------------------------------------------------------------------
# async_handle_adapter_errors
# ---------------------------------------------------------------------------


class TestAsyncHandleAdapterErrors:
    def test_return_value_preserved(self) -> None:
        @async_handle_adapter_errors("op")
        async def fn() -> int:
            return 9

        assert asyncio.run(fn()) == 9

    def test_exception_swallowed_returns_none(self) -> None:
        @async_handle_adapter_errors("op")
        async def fn() -> None:
            raise RuntimeError("async boom")

        assert asyncio.run(fn()) is None

    def test_reraise(self) -> None:
        @async_handle_adapter_errors("op", reraise=True)
        async def fn() -> None:
            raise RuntimeError("async boom")

        with pytest.raises(DapperError):
            asyncio.run(fn())


# ---------------------------------------------------------------------------
# async_handle_backend_errors
# ---------------------------------------------------------------------------


class TestAsyncHandleBackendErrors:
    def test_return_value_preserved(self) -> None:
        @async_handle_backend_errors("op")
        async def fn() -> str:
            return "done"

        assert asyncio.run(fn()) == "done"

    def test_exception_swallowed_returns_none(self) -> None:
        @async_handle_backend_errors("op")
        async def fn() -> None:
            raise RuntimeError("async backend fail")

        assert asyncio.run(fn()) is None

    def test_reraise(self) -> None:
        @async_handle_backend_errors("op", reraise=True)
        async def fn() -> None:
            raise RuntimeError("async backend fail")

        with pytest.raises(BackendError):
            asyncio.run(fn())


# ---------------------------------------------------------------------------
# async_handle_debugger_errors
# ---------------------------------------------------------------------------


class TestAsyncHandleDebuggerErrors:
    def test_return_value_preserved(self) -> None:
        @async_handle_debugger_errors("resume")
        async def fn() -> int:
            return 3

        assert asyncio.run(fn()) == 3

    def test_exception_swallowed_returns_none(self) -> None:
        @async_handle_debugger_errors("resume")
        async def fn() -> None:
            raise RuntimeError("async debugger fail")

        assert asyncio.run(fn()) is None

    def test_reraise(self) -> None:
        @async_handle_debugger_errors("resume", reraise=True)
        async def fn() -> None:
            raise RuntimeError("async debugger fail")

        with pytest.raises(DebuggerError):
            asyncio.run(fn())


# ---------------------------------------------------------------------------
# ErrorContext
# ---------------------------------------------------------------------------


class TestErrorContext:
    def test_no_exception_passes_through(self) -> None:
        x = 0
        with ErrorContext("test_op"):
            x = 1 + 1

        assert x == 2

    def test_exception_is_wrapped(self) -> None:
        with pytest.raises(DapperError) as exc_info, ErrorContext("test_op"):
            raise RuntimeError("inner")

        assert "inner" in str(exc_info.value)
        assert "test_op" in str(exc_info.value)

    def test_dapper_error_is_not_double_wrapped(self) -> None:
        original = IPCError("already wrapped")
        with pytest.raises(IPCError) as exc_info, ErrorContext("test_op"):
            raise original

        # Should re-raise the original or log without re-wrapping in a new type
        # The implementation logs then re-raises: check it's still an IPCError
        assert exc_info.value is original

    def test_custom_error_type_used_for_wrapping(self) -> None:
        with pytest.raises(ProtocolError), ErrorContext("test_op", error_type=ProtocolError):
            raise RuntimeError("inner")

    def test_context_kwargs_included_in_details(self) -> None:
        with (
            pytest.raises(DapperError) as exc_info,
            ErrorContext("test_op", cmd="continue", seq=5),
        ):
            raise RuntimeError("inner")

        assert exc_info.value.details.get("cmd") == "continue"
        assert exc_info.value.details.get("seq") == 5

    def test_system_exit_not_suppressed(self) -> None:
        with pytest.raises(SystemExit), ErrorContext("test_op"):
            raise SystemExit(1)
