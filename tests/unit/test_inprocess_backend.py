"""Unit tests for InProcessBackend."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dapper.adapter.inprocess_backend import InProcessBackend


def _make_bridge(**methods: Any) -> MagicMock:
    """Return a MagicMock bridge with named methods pre-configured."""
    bridge = MagicMock()
    for name, value in methods.items():
        if callable(value) and not isinstance(value, MagicMock):
            setattr(bridge, name, value)
        else:
            getattr(bridge, name).return_value = value
    return bridge


def _backend(bridge: MagicMock | None = None) -> InProcessBackend:
    if bridge is None:
        bridge = MagicMock()
    return InProcessBackend(bridge)


class TestBridgeProperty:
    def test_exposes_bridge(self) -> None:
        bridge = MagicMock()
        backend = _backend(bridge)
        assert backend.bridge is bridge


class TestIsAvailable:
    def test_true_after_construction(self) -> None:
        # Lifecycle starts in INITIALIZED state which is "available"
        assert _backend().is_available() is True

    def test_false_after_lifecycle_error(self) -> None:
        backend = _backend()
        lifecycle_mock = MagicMock()
        lifecycle_mock.is_available = False
        backend._lifecycle = lifecycle_mock  # type: ignore[assignment]
        assert backend.is_available() is False


class TestSetBreakpoints:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        bps = [{"line": 5}, {"line": 10}]
        bridge = _make_bridge()
        bridge.set_breakpoints.return_value = [{"verified": True, "line": 5}]
        backend = _backend(bridge)
        result = await backend.set_breakpoints("/a.py", bps)  # type: ignore[arg-type]
        bridge.set_breakpoints.assert_called_once_with("/a.py", bps)
        assert result == [{"verified": True, "line": 5}]

    @pytest.mark.asyncio
    async def test_returns_unverified_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_breakpoints.side_effect = RuntimeError("oops")
        backend = _backend(bridge)
        result = await backend.set_breakpoints("/a.py", [{"line": 1}, {"line": 2}])
        assert result == [{"verified": False}, {"verified": False}]


class TestSetFunctionBreakpoints:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        bps = [{"name": "my_func"}]
        bridge = _make_bridge()
        bridge.set_function_breakpoints.return_value = [{"verified": True}]
        backend = _backend(bridge)
        result = await backend.set_function_breakpoints(bps)  # type: ignore[arg-type]
        bridge.set_function_breakpoints.assert_called_once_with(bps)
        assert result == [{"verified": True}]

    @pytest.mark.asyncio
    async def test_returns_unverified_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_function_breakpoints.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.set_function_breakpoints([{"name": "f1"}, {"name": "f2"}])
        assert result == [{"verified": False}, {"verified": False}]


class TestSetExceptionBreakpoints:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        bridge = _make_bridge()
        bridge.set_exception_breakpoints.return_value = [{"verified": True}]
        backend = _backend(bridge)
        result = await backend.set_exception_breakpoints(["raised"])
        bridge.set_exception_breakpoints.assert_called_once_with(["raised"])
        assert result == [{"verified": True}]

    @pytest.mark.asyncio
    async def test_returns_unverified_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_exception_breakpoints.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.set_exception_breakpoints(["a", "b"])
        assert result == [{"verified": False}, {"verified": False}]

    @pytest.mark.asyncio
    async def test_ignores_filter_options_and_exception_options(self) -> None:
        bridge = _make_bridge()
        bridge.set_exception_breakpoints.return_value = []
        backend = _backend(bridge)
        # Should not raise even when extra args are supplied
        await backend.set_exception_breakpoints(
            ["raised"],
            filter_options=[{"filterId": "raised"}],
            exception_options=[{"path": []}],
        )
        bridge.set_exception_breakpoints.assert_called_once_with(["raised"])


class TestContinue:
    @pytest.mark.asyncio
    async def test_returns_all_threads_continued_true_by_default(self) -> None:
        bridge = _make_bridge()
        bridge.continue_.return_value = {"allThreadsContinued": True}
        backend = _backend(bridge)
        result = await backend.continue_(1)
        assert result == {"allThreadsContinued": True}

    @pytest.mark.asyncio
    async def test_returns_false_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.continue_.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.continue_(1)
        assert result == {"allThreadsContinued": False}


class TestStepCommands:
    @pytest.mark.asyncio
    async def test_next_delegates_to_bridge(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)
        await backend.next_(2, granularity="statement")
        bridge.next_.assert_called_once_with(2, granularity="statement")

    @pytest.mark.asyncio
    async def test_next_swallows_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.next_.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        await backend.next_(1)  # must not raise

    @pytest.mark.asyncio
    async def test_step_in_delegates_to_bridge(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)
        await backend.step_in(3, target_id=7, granularity="instruction")
        bridge.step_in.assert_called_once_with(3, 7, granularity="instruction")

    @pytest.mark.asyncio
    async def test_step_in_swallows_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.step_in.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        await backend.step_in(1)  # must not raise

    @pytest.mark.asyncio
    async def test_step_out_delegates_to_bridge(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)
        await backend.step_out(4, granularity="line")
        bridge.step_out.assert_called_once_with(4, granularity="line")

    @pytest.mark.asyncio
    async def test_step_out_swallows_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.step_out.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        await backend.step_out(1)  # must not raise


class TestPause:
    @pytest.mark.asyncio
    async def test_always_returns_false(self) -> None:
        backend = _backend()
        assert await backend.pause(1) is False

    @pytest.mark.asyncio
    async def test_does_not_call_bridge(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)
        await backend.pause(1)
        bridge.pause.assert_not_called()


class TestGetStackTrace:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        expected = {"stackFrames": [{"id": 1}], "totalFrames": 1}
        bridge = _make_bridge()
        bridge.stack_trace.return_value = expected
        backend = _backend(bridge)
        result = await backend.get_stack_trace(1, 0, 5)
        bridge.stack_trace.assert_called_once_with(1, 0, 5)
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_frames_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.stack_trace.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.get_stack_trace(1)
        assert result == {"stackFrames": [], "totalFrames": 0}


class TestGetVariables:
    @pytest.mark.asyncio
    async def test_delegates_with_positive_start_and_count(self) -> None:
        vars_ = [{"name": "x", "value": "1", "variablesReference": 0}]
        bridge = _make_bridge()
        bridge.variables.return_value = vars_
        backend = _backend(bridge)
        result = await backend.get_variables(5, "named", 2, 10)
        bridge.variables.assert_called_once_with(5, filter_type="named", start=2, count=10)
        assert result == vars_

    @pytest.mark.asyncio
    async def test_passes_none_for_zero_start_and_count(self) -> None:
        bridge = _make_bridge()
        bridge.variables.return_value = []
        backend = _backend(bridge)
        await backend.get_variables(1, "", 0, 0)
        bridge.variables.assert_called_once_with(1, filter_type=None, start=None, count=None)

    @pytest.mark.asyncio
    async def test_passes_none_for_empty_filter_type(self) -> None:
        bridge = _make_bridge()
        bridge.variables.return_value = []
        backend = _backend(bridge)
        await backend.get_variables(1, "")
        _, kwargs = bridge.variables.call_args
        assert kwargs["filter_type"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.variables.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.get_variables(1)
        assert result == []


class TestSetVariable:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        expected = {"value": "42", "type": "int", "variablesReference": 0}
        bridge = _make_bridge()
        bridge.set_variable.return_value = expected
        backend = _backend(bridge)
        result = await backend.set_variable(3, "x", "42")
        bridge.set_variable.assert_called_once_with(3, "x", "42")
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_fallback_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_variable.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.set_variable(1, "z", "abc")
        assert result["value"] == "abc"
        assert result.get("variablesReference") == 0


class TestSetExpression:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        expected = {"value": "5", "type": "int", "variablesReference": 0}
        bridge = _make_bridge()
        bridge.set_expression.return_value = expected
        backend = _backend(bridge)
        result = await backend.set_expression("x", "5", 3)
        bridge.set_expression.assert_called_once_with("x", "5", 3)
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_fallback_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_expression.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.set_expression("y", "99", None)
        assert result["value"] == "99"


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        expected = {"result": "42", "type": "int", "variablesReference": 0}
        bridge = _make_bridge()
        bridge.evaluate.return_value = expected
        backend = _backend(bridge)
        result = await backend.evaluate("21+21", frame_id=2, context="repl")
        bridge.evaluate.assert_called_once_with("21+21", 2, "repl")
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_placeholder_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.evaluate.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.evaluate("foo")
        assert "foo" in result.get("result", "")
        assert result.get("variablesReference") == 0


class TestCompletions:
    @pytest.mark.asyncio
    async def test_delegates_to_bridge(self) -> None:
        expected = {"targets": [{"label": "path"}]}
        bridge = _make_bridge()
        bridge.completions.return_value = expected
        backend = _backend(bridge)
        result = await backend.completions("os.", 3, frame_id=1, line=2)
        bridge.completions.assert_called_once_with("os.", 3, 1, 2)
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_targets_on_bridge_error(self) -> None:
        bridge = _make_bridge()
        bridge.completions.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.completions("x", 1)
        assert result == {"targets": []}


class TestExceptionInfo:
    @pytest.mark.asyncio
    async def test_returns_exception_info_from_bridge(self) -> None:
        bridge = _make_bridge()
        bridge.get_exception_info.return_value = {
            "exceptionId": "ValueError",
            "description": "bad value",
            "breakMode": "always",
        }
        backend = _backend(bridge)
        result = await backend.exception_info(1)
        assert result.get("exceptionId") == "ValueError"
        assert result.get("description") == "bad value"
        assert result.get("breakMode") == "always"

    @pytest.mark.asyncio
    async def test_returns_fallback_when_bridge_returns_none(self) -> None:
        bridge = _make_bridge()
        bridge.get_exception_info.return_value = None
        backend = _backend(bridge)
        result = await backend.exception_info(1)
        assert result.get("exceptionId") == "Unknown"
        assert "No exception" in result.get("description", "")

    @pytest.mark.asyncio
    async def test_returns_fallback_when_bridge_raises(self) -> None:
        bridge = _make_bridge()
        bridge.get_exception_info.side_effect = RuntimeError("fail")
        backend = _backend(bridge)
        result = await backend.exception_info(1)
        assert result.get("exceptionId") == "Unknown"

    @pytest.mark.asyncio
    async def test_includes_details_from_bridge(self) -> None:
        bridge = _make_bridge()
        bridge.get_exception_info.return_value = {
            "exceptionId": "KeyError",
            "description": "missing key",
            "breakMode": "unhandled",
            "details": {"message": "key not found"},
        }
        backend = _backend(bridge)
        result = await backend.exception_info(1)
        assert result.get("details", {}).get("message") == "key not found"

    @pytest.mark.asyncio
    async def test_fills_in_missing_details_from_exception_id(self) -> None:
        bridge = _make_bridge()
        bridge.get_exception_info.return_value = {
            "exceptionId": "TypeError",
            "description": "type mismatch",
            "breakMode": "always",
            # no "details" key
        }
        backend = _backend(bridge)
        result = await backend.exception_info(1)
        # The auto-generated details should reference the exceptionId
        assert result.get("details", {}).get("typeName") == "TypeError"


class TestConfigurationDone:
    @pytest.mark.asyncio
    async def test_is_noop(self) -> None:
        backend = _backend()
        await backend.configuration_done()  # must not raise


class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_wraps_non_value_errors_as_value_error(self) -> None:
        bridge = _make_bridge()
        bridge.set_breakpoints.side_effect = OSError("disk full")
        backend = _backend(bridge)

        # Force an unhandled error path by patching the handler directly
        async def _exploding_handler(_args: dict) -> dict:
            raise OSError("disk full")

        backend._dispatch_map["set_breakpoints"] = _exploding_handler  # type: ignore[assignment]

        with pytest.raises(ValueError, match=r"set_breakpoints.*failed"):
            await backend._execute_command(
                "set_breakpoints",
                {"path": "/f.py", "breakpoints": []},
            )

    @pytest.mark.asyncio
    async def test_reraises_value_errors_directly(self) -> None:
        backend = _backend()

        async def _raising_handler(_args: dict) -> dict:
            raise ValueError("explicit value error")

        backend._dispatch_map["set_breakpoints"] = _raising_handler  # type: ignore[assignment]

        with pytest.raises(ValueError, match="explicit value error"):
            await backend._execute_command(
                "set_breakpoints",
                {"path": "/f.py", "breakpoints": []},
            )


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_marks_backend_ready(self) -> None:
        backend = _backend()
        await backend.initialize()
        assert backend._lifecycle.is_available

    @pytest.mark.asyncio
    async def test_launch_calls_initialize(self) -> None:
        backend = _backend()
        called = []
        original = backend.initialize

        async def _spy() -> None:
            called.append(True)
            await original()

        backend.initialize = _spy  # type: ignore[method-assign]
        await backend.launch(MagicMock())
        assert called

    @pytest.mark.asyncio
    async def test_attach_calls_initialize(self) -> None:
        backend = _backend()
        called = []
        original = backend.initialize

        async def _spy() -> None:
            called.append(True)
            await original()

        backend.initialize = _spy  # type: ignore[method-assign]
        await backend.attach(MagicMock())
        assert called

    @pytest.mark.asyncio
    async def test_terminate_completes_lifecycle(self) -> None:
        backend = _backend()
        await backend.initialize()
        await backend.terminate()
        # After termination the lifecycle should no longer be available
        assert not backend.is_available()


class TestBuildDispatchTable:
    def test_contains_all_dispatch_keys(self) -> None:
        backend = _backend()
        table = backend._build_dispatch_table({})
        for key in backend._dispatch_map:
            assert key in table

    @pytest.mark.asyncio
    async def test_zero_arg_callables_forward_args(self) -> None:
        bridge = _make_bridge()
        bridge.set_breakpoints.return_value = [{"verified": True, "line": 7}]
        backend = _backend(bridge)
        table = backend._build_dispatch_table({"path": "/x.py", "breakpoints": [{"line": 7}]})
        result = await table["set_breakpoints"]()
        assert result == {"breakpoints": [{"verified": True, "line": 7}]}


class TestHandlerMethods:
    @pytest.mark.asyncio
    async def test_handler_set_breakpoints_wraps_in_dict(self) -> None:
        bridge = _make_bridge()
        bridge.set_breakpoints.return_value = [{"verified": True}]
        backend = _backend(bridge)
        result = await backend._handler_set_breakpoints(
            {"path": "/a.py", "breakpoints": [{"line": 1}]}
        )
        assert "breakpoints" in result

    @pytest.mark.asyncio
    async def test_handler_pause_embeds_sent_flag(self) -> None:
        backend = _backend()
        result = await backend._handler_pause({"thread_id": 1})
        assert "sent" in result
        assert result["sent"] is False

    @pytest.mark.asyncio
    async def test_handler_goto_targets_wraps_in_dict(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)
        targets_out = [{"id": 1, "label": "L5", "line": 5}]

        # Stub the public method to avoid the lifecycle-busy guard
        async def _fake_goto_targets(frame_id: int, line: int):
            return targets_out

        backend.goto_targets = _fake_goto_targets  # type: ignore[method-assign]
        result = await backend._handler_goto_targets({"frame_id": 1, "line": 5})
        assert result["targets"] == targets_out

    @pytest.mark.asyncio
    async def test_handler_goto_returns_empty_dict(self) -> None:
        bridge = _make_bridge()
        backend = _backend(bridge)

        async def _fake_goto(thread_id: int, target_id: int) -> None:
            return None

        backend.goto = _fake_goto  # type: ignore[method-assign]
        result = await backend._handler_goto({"thread_id": 1, "target_id": 3})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handler_configuration_done_returns_empty_dict(self) -> None:
        backend = _backend()
        result = await backend._handler_configuration_done({})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handler_terminate_returns_empty_dict(self) -> None:
        backend = _backend()
        await backend.initialize()
        result = await backend._handler_terminate({})
        assert result == {}
