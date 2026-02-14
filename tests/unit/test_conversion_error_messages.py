from __future__ import annotations

from types import SimpleNamespace

from dapper.shared import command_handlers as handlers


def test_set_scope_variable_conversion_failure_message_is_standardized():
    frame = SimpleNamespace(f_locals={}, f_globals={})
    result = handlers._set_scope_variable(frame, "locals", "x", object())
    assert result["success"] is False
    assert result["message"] == "Conversion failed"


def test_format_evaluation_error_messages_are_standardized():
    blocked = handlers._format_evaluation_error(ValueError("expression blocked by policy"))
    generic = handlers._format_evaluation_error(RuntimeError("name 'x' is not defined"))
    assert blocked == "<error: Evaluation blocked by policy>"
    assert generic == "<error: Evaluation failed>"
