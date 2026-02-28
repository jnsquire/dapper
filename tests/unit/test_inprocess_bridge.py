"""Unit tests for InProcessBridge."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dapper.adapter.inprocess_bridge import InProcessBridge


def _make_inproc(**attrs: Any) -> MagicMock:
    """Return a MagicMock InProcessDebugger with event-signal stubs."""
    inproc = MagicMock()
    # Each on_* attribute needs an add_listener method so __init__ can register
    for attr in ("on_stopped", "on_thread", "on_exited", "on_output"):
        signal = MagicMock()
        signal.add_listener = MagicMock()
        setattr(inproc, attr, signal)
    for key, val in attrs.items():
        setattr(inproc, key, val)
    return inproc


def _make_bridge(inproc: MagicMock | None = None, **handlers: Any) -> InProcessBridge:
    if inproc is None:
        inproc = _make_inproc()
    return InProcessBridge(
        inproc,
        on_stopped=handlers.get("on_stopped", MagicMock()),
        on_thread=handlers.get("on_thread", MagicMock()),
        on_exited=handlers.get("on_exited", MagicMock()),
        on_output=handlers.get("on_output", MagicMock()),
    )


class TestInit:
    def test_registers_all_four_event_listeners(self) -> None:
        inproc = _make_inproc()
        bridge = _make_bridge(inproc)
        inproc.on_stopped.add_listener.assert_called_once_with(bridge._handle_stopped)
        inproc.on_thread.add_listener.assert_called_once_with(bridge._handle_thread)
        inproc.on_exited.add_listener.assert_called_once_with(bridge._handle_exited)
        inproc.on_output.add_listener.assert_called_once_with(bridge._handle_output)

    def test_stores_inproc_reference(self) -> None:
        inproc = _make_inproc()
        bridge = _make_bridge(inproc)
        assert bridge._inproc is inproc


class TestGetattr:
    def test_delegates_unknown_attribute_to_inproc(self) -> None:
        inproc = _make_inproc()
        inproc.some_custom_method = MagicMock(return_value=42)
        bridge = _make_bridge(inproc)
        assert bridge.some_custom_method() == 42

    def test_raises_attribute_error_for_inproc_before_set(self) -> None:
        bridge = InProcessBridge.__new__(InProcessBridge)
        with pytest.raises(AttributeError):
            _ = bridge._inproc


class TestDebuggerProperty:
    def test_returns_underlying_inproc(self) -> None:
        inproc = _make_inproc()
        bridge = _make_bridge(inproc)
        assert bridge.debugger is inproc


class TestEventHandlers:
    def test_handle_stopped_calls_on_stopped(self) -> None:
        on_stopped = MagicMock()
        bridge = _make_bridge(on_stopped=on_stopped)
        data = {"threadId": 1, "reason": "breakpoint"}
        bridge._handle_stopped(data)
        on_stopped.assert_called_once_with(data)

    def test_handle_stopped_swallows_callback_exception(self) -> None:
        on_stopped = MagicMock(side_effect=RuntimeError("boom"))
        bridge = _make_bridge(on_stopped=on_stopped)
        bridge._handle_stopped({})  # must not raise

    def test_handle_thread_calls_on_thread(self) -> None:
        on_thread = MagicMock()
        bridge = _make_bridge(on_thread=on_thread)
        data = {"threadId": 2, "reason": "started"}
        bridge._handle_thread(data)
        on_thread.assert_called_once_with(data)

    def test_handle_thread_swallows_callback_exception(self) -> None:
        on_thread = MagicMock(side_effect=RuntimeError("boom"))
        bridge = _make_bridge(on_thread=on_thread)
        bridge._handle_thread({})  # must not raise

    def test_handle_exited_calls_on_exited(self) -> None:
        on_exited = MagicMock()
        bridge = _make_bridge(on_exited=on_exited)
        data = {"exitCode": 0}
        bridge._handle_exited(data)
        on_exited.assert_called_once_with(data)

    def test_handle_exited_swallows_callback_exception(self) -> None:
        on_exited = MagicMock(side_effect=RuntimeError("boom"))
        bridge = _make_bridge(on_exited=on_exited)
        bridge._handle_exited({})  # must not raise

    def test_handle_output_calls_on_output(self) -> None:
        on_output = MagicMock()
        bridge = _make_bridge(on_output=on_output)
        bridge._handle_output("stdout", "hello")
        on_output.assert_called_once_with("stdout", "hello")

    def test_handle_output_swallows_callback_exception(self) -> None:
        on_output = MagicMock(side_effect=RuntimeError("boom"))
        bridge = _make_bridge(on_output=on_output)
        bridge._handle_output("stderr", "err")  # must not raise


class TestSetFunctionBreakpoints:
    def test_delegates_and_returns_list(self) -> None:
        inproc = _make_inproc()
        bps = [{"name": "my_func"}]
        inproc.set_function_breakpoints.return_value = bps
        bridge = _make_bridge(inproc)
        result = bridge.set_function_breakpoints(bps)  # type: ignore[arg-type]
        inproc.set_function_breakpoints.assert_called_once_with(bps)
        assert result == bps

    def test_always_returns_a_new_list(self) -> None:
        inproc = _make_inproc()
        original = [{"name": "f"}]
        inproc.set_function_breakpoints.return_value = original
        bridge = _make_bridge(inproc)
        result = bridge.set_function_breakpoints(original)  # type: ignore[arg-type]
        assert result is not original


class TestSetExceptionBreakpoints:
    def test_delegates_and_returns_list(self) -> None:
        inproc = _make_inproc()
        inproc.set_exception_breakpoints.return_value = [{"verified": True}]
        bridge = _make_bridge(inproc)
        result = bridge.set_exception_breakpoints(["raised"])
        inproc.set_exception_breakpoints.assert_called_once_with(["raised"])
        assert result == [{"verified": True}]

    def test_always_returns_a_new_list(self) -> None:
        inproc = _make_inproc()
        original = [{"verified": True}]
        inproc.set_exception_breakpoints.return_value = original
        bridge = _make_bridge(inproc)
        result = bridge.set_exception_breakpoints(["raised"])
        assert result is not original


class TestVariables:
    def test_passes_kwargs_to_inproc(self) -> None:
        inproc = _make_inproc()
        inproc.variables.return_value = []
        bridge = _make_bridge(inproc)
        bridge.variables(5, filter_type="named", start=2, count=10)
        inproc.variables.assert_called_once_with(5, _filter="named", _start=2, _count=10)

    def test_returns_list_directly(self) -> None:
        inproc = _make_inproc()
        vars_ = [{"name": "x", "value": "1", "variablesReference": 0}]
        inproc.variables.return_value = vars_
        bridge = _make_bridge(inproc)
        assert bridge.variables(1) == vars_

    def test_extracts_variables_from_dict_response(self) -> None:
        inproc = _make_inproc()
        vars_ = [{"name": "y", "value": "2", "variablesReference": 0}]
        inproc.variables.return_value = {"variables": vars_, "totalCount": 1}
        bridge = _make_bridge(inproc)
        assert bridge.variables(1) == vars_

    def test_returns_empty_list_when_dict_has_no_variables_key(self) -> None:
        inproc = _make_inproc()
        inproc.variables.return_value = {"unexpected": True}
        bridge = _make_bridge(inproc)
        assert bridge.variables(1) == []

    def test_defaults_all_kwargs_to_none(self) -> None:
        inproc = _make_inproc()
        inproc.variables.return_value = []
        bridge = _make_bridge(inproc)
        bridge.variables(3)
        inproc.variables.assert_called_once_with(3, _filter=None, _start=None, _count=None)


class TestSetVariable:
    def test_delegates_to_inproc(self) -> None:
        inproc = _make_inproc()
        inproc.set_variable.return_value = {"value": "42", "type": "int", "variablesReference": 0}
        bridge = _make_bridge(inproc)
        result = bridge.set_variable(1, "x", "42")
        inproc.set_variable.assert_called_once_with(1, "x", "42")
        assert result["value"] == "42"


class TestSetExpression:
    def test_delegates_to_inproc(self) -> None:
        inproc = _make_inproc()
        inproc.set_expression.return_value = {"value": "5", "type": "int", "variablesReference": 0}
        bridge = _make_bridge(inproc)
        result = bridge.set_expression("x", "5", 3)
        inproc.set_expression.assert_called_once_with("x", "5", 3)
        assert result["value"] == "5"


class TestCompletions:
    def test_delegates_to_inproc(self) -> None:
        inproc = _make_inproc()
        inproc.completions.return_value = {"targets": [{"label": "path"}]}
        bridge = _make_bridge(inproc)
        result = bridge.completions("os.", 3, 1, 2)
        inproc.completions.assert_called_once_with("os.", 3, 1, 2)
        assert result["targets"] == [{"label": "path"}]


class TestDispatchCommand:
    def _bridge_with_tracked_inproc(self) -> tuple[InProcessBridge, MagicMock]:
        inproc = _make_inproc()
        return _make_bridge(inproc), inproc

    def test_continue_dispatches(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "continue", "arguments": {"threadId": 2}})
        inproc.continue_.assert_called_once_with(2)

    def test_next_dispatches(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "next", "arguments": {"threadId": 3}})
        inproc.next_.assert_called_once_with(3)

    def test_step_in_dispatches(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "stepIn", "arguments": {"threadId": 1}})
        inproc.step_in.assert_called_once_with(1)

    def test_step_out_dispatches(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "stepOut", "arguments": {"threadId": 1}})
        inproc.step_out.assert_called_once_with(1)

    def test_goto_targets_returns_targets_in_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.goto_targets.return_value = [{"id": 5}]
        result = bridge.dispatch_command(
            {"command": "gotoTargets", "arguments": {"frameId": 2, "line": 10}},
            expect_response=True,
        )
        assert result is not None
        assert result["body"]["targets"] == [{"id": 5}]

    def test_goto_dispatches(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "goto", "arguments": {"threadId": 1, "targetId": 7}})
        inproc.goto.assert_called_once_with(1, 7)

    def test_stack_trace_returns_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        trace = {"stackFrames": [{"id": 1}], "totalFrames": 1}
        inproc.stack_trace.return_value = trace
        result = bridge.dispatch_command(
            {"command": "stackTrace", "arguments": {"threadId": 1}},
            expect_response=True,
        )
        assert result is not None
        assert result["body"] == trace

    def test_variables_returns_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.variables.return_value = [{"name": "x"}]
        result = bridge.dispatch_command(
            {"command": "variables", "arguments": {"variablesReference": 3}},
            expect_response=True,
        )
        assert result is not None
        assert result["body"] == [{"name": "x"}]

    def test_set_variable_returns_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.set_variable.return_value = {"value": "9"}
        result = bridge.dispatch_command(
            {
                "command": "setVariable",
                "arguments": {"variablesReference": 1, "name": "x", "value": "9"},
            },
            expect_response=True,
        )
        assert result is not None
        assert result["body"]["value"] == "9"

    def test_set_expression_returns_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.set_expression.return_value = {"value": "5"}
        result = bridge.dispatch_command(
            {
                "command": "setExpression",
                "arguments": {"expression": "x", "value": "5"},
            },
            expect_response=True,
        )
        assert result is not None
        assert result["body"]["value"] == "5"

    def test_evaluate_returns_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.evaluate.return_value = {"result": "42"}
        result = bridge.dispatch_command(
            {"command": "evaluate", "arguments": {"expression": "21+21"}},
            expect_response=True,
        )
        assert result is not None
        assert result["body"]["result"] == "42"

    def test_exception_info_returns_placeholder_body(self) -> None:
        bridge, _ = self._bridge_with_tracked_inproc()
        result = bridge.dispatch_command(
            {"command": "exceptionInfo", "arguments": {"threadId": 1}},
            expect_response=True,
        )
        assert result is not None
        assert result["body"]["exceptionId"] == "Unknown"

    def test_configuration_done_returns_none(self) -> None:
        bridge, _ = self._bridge_with_tracked_inproc()
        result = bridge.dispatch_command({"command": "configurationDone"})
        assert result is None

    def test_terminate_returns_none(self) -> None:
        bridge, _ = self._bridge_with_tracked_inproc()
        result = bridge.dispatch_command({"command": "terminate"})
        assert result is None

    def test_pause_returns_none(self) -> None:
        bridge, _ = self._bridge_with_tracked_inproc()
        result = bridge.dispatch_command({"command": "pause"})
        assert result is None

    def test_unknown_command_returns_none(self) -> None:
        bridge, _ = self._bridge_with_tracked_inproc()
        result = bridge.dispatch_command({"command": "noop"})
        assert result is None

    def test_expect_response_false_returns_none_even_with_body(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.stack_trace.return_value = {"stackFrames": []}
        result = bridge.dispatch_command(
            {"command": "stackTrace", "arguments": {"threadId": 1}},
            expect_response=False,
        )
        assert result is None

    def test_exception_during_dispatch_returns_empty_body_when_response_expected(
        self,
    ) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.continue_.side_effect = RuntimeError("boom")
        result = bridge.dispatch_command(
            {"command": "continue", "arguments": {"threadId": 1}},
            expect_response=True,
        )
        assert result == {"body": {}}

    def test_exception_during_dispatch_returns_none_when_no_response_expected(
        self,
    ) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        inproc.continue_.side_effect = RuntimeError("boom")
        result = bridge.dispatch_command(
            {"command": "continue", "arguments": {"threadId": 1}},
            expect_response=False,
        )
        assert result is None

    def test_thread_id_defaults_to_one_when_missing(self) -> None:
        bridge, inproc = self._bridge_with_tracked_inproc()
        bridge.dispatch_command({"command": "continue", "arguments": {}})
        inproc.continue_.assert_called_once_with(1)


class TestGetExceptionInfo:
    def _bridge_with_exception_handler(self, info_map: dict[int, Any]) -> InProcessBridge:
        inproc = _make_inproc()
        exc_handler = MagicMock()
        exc_handler.exception_info_by_thread = info_map
        inproc.debugger = MagicMock()
        inproc.debugger.exception_handler = exc_handler
        return _make_bridge(inproc)

    def test_returns_none_when_no_info_for_thread(self) -> None:
        bridge = self._bridge_with_exception_handler({})
        assert bridge.get_exception_info(1) is None

    def test_returns_none_when_info_is_not_a_dict(self) -> None:
        bridge = self._bridge_with_exception_handler({1: "not a dict"})
        assert bridge.get_exception_info(1) is None

    def test_returns_none_when_info_map_is_not_a_dict(self) -> None:
        inproc = _make_inproc()
        exc_handler = MagicMock()
        exc_handler.exception_info_by_thread = "not a dict"
        inproc.debugger = MagicMock()
        inproc.debugger.exception_handler = exc_handler
        bridge = _make_bridge(inproc)
        assert bridge.get_exception_info(1) is None

    def test_maps_known_fields(self) -> None:
        info = {
            "exceptionId": "ValueError",
            "description": "bad value",
            "breakMode": "always",
            "details": {"message": "oops"},
        }
        bridge = self._bridge_with_exception_handler({1: info})
        result = bridge.get_exception_info(1)
        assert result is not None
        assert result.get("exceptionId") == "ValueError"
        assert result.get("description") == "bad value"
        assert result.get("breakMode") == "always"
        assert result.get("details") == {"message": "oops"}

    def test_omits_missing_optional_fields(self) -> None:
        bridge = self._bridge_with_exception_handler({1: {"exceptionId": "KeyError"}})
        result = bridge.get_exception_info(1)
        assert result is not None
        assert "description" not in result
        assert "breakMode" not in result

    def test_skips_details_when_not_a_dict(self) -> None:
        bridge = self._bridge_with_exception_handler(
            {1: {"exceptionId": "E", "details": "not a dict"}}
        )
        result = bridge.get_exception_info(1)
        assert result is not None
        assert "details" not in result

    def test_returns_none_on_exception(self) -> None:
        inproc = _make_inproc()
        inproc.debugger = MagicMock()
        inproc.debugger.exception_handler = MagicMock(side_effect=RuntimeError("broken"))
        bridge = _make_bridge(inproc)
        # Accessing .exception_handler raises, so get_exception_info should
        # catch and return None.
        assert bridge.get_exception_info(1) is None


class TestRegisterDataWatches:
    def test_calls_register_when_available(self) -> None:
        inproc = _make_inproc()
        register = MagicMock()
        inner_dbg = MagicMock()
        inner_dbg.register_data_watches = register
        inproc.debugger = inner_dbg
        bridge = _make_bridge(inproc)
        bridge.register_data_watches(["x"], [("x", {})], ["x > 0"], [("x > 0", {})])
        register.assert_called_once_with(["x"], [("x", {})], ["x > 0"], [("x > 0", {})])

    def test_defaults_expression_args_to_empty_lists(self) -> None:
        inproc = _make_inproc()
        register = MagicMock()
        inner_dbg = MagicMock()
        inner_dbg.register_data_watches = register
        inproc.debugger = inner_dbg
        bridge = _make_bridge(inproc)
        bridge.register_data_watches(["y"], [("y", {})])
        register.assert_called_once_with(["y"], [("y", {})], [], [])

    def test_noop_when_register_not_available(self) -> None:
        inproc = _make_inproc()
        inner_dbg = MagicMock(spec=[])  # no register_data_watches
        inproc.debugger = inner_dbg
        bridge = _make_bridge(inproc)
        bridge.register_data_watches(["z"], [("z", {})])  # must not raise

    def test_swallows_exceptions_from_register(self) -> None:
        inproc = _make_inproc()
        register = MagicMock(side_effect=RuntimeError("fail"))
        inner_dbg = MagicMock()
        inner_dbg.register_data_watches = register
        inproc.debugger = inner_dbg
        bridge = _make_bridge(inproc)
        bridge.register_data_watches(["x"], [("x", {})])  # must not raise
