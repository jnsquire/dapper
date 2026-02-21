from __future__ import annotations

from types import SimpleNamespace

from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers as handlers
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context

_CONVERSION_FAILED = object()


def _try_test_convert(value_str, frame=None, parent_obj=None):
    try:
        return convert_value_with_context(value_str, frame, parent_obj)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        return _CONVERSION_FAILED


def _make_variable_for_tests(dbg, name, value, frame):
    return command_handler_helpers.make_variable(
        dbg,
        name,
        value,
        frame,
    )


def test_set_scope_variable_conversion_failure_message_is_standardized():
    frame = SimpleNamespace(f_locals={}, f_globals={})
    result = command_handler_helpers.set_scope_variable(
        frame,
        "locals",
        "x",
        object(),
        try_custom_convert=_try_test_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        evaluate_with_policy_fn=handlers.evaluate_with_policy,
        convert_value_with_context_fn=convert_value_with_context,
        logger=handlers.logger,
        error_response_fn=handlers._error_response,
        conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=lambda: None,
        make_variable_fn=_make_variable_for_tests,
    )
    assert result["success"] is False
    assert result["message"] == "Conversion failed"


def test_format_evaluation_error_messages_are_standardized():
    blocked = variable_handlers.format_evaluation_error(ValueError("expression blocked by policy"))
    generic = variable_handlers.format_evaluation_error(RuntimeError("name 'x' is not defined"))
    assert blocked == "<error: Evaluation blocked by policy>"
    assert generic == "<error: Evaluation failed>"
