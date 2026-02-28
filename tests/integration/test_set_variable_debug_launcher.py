"""Test for setVariable functionality in debug_launcher.py"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers
from dapper.shared import variable_handlers

# Import the specific functions we want to test
from dapper.shared.debug_shared import DebugSession
from dapper.shared.debug_shared import make_variable_object
from dapper.shared.value_conversion import convert_value_with_context

_CONVERSION_FAILED = object()


def _try_convert(value_str, frame=None, parent_obj=None):
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


class TestSetVariable(unittest.TestCase):
    """Test setVariable functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock debugger
        self.mock_debugger = Mock()
        self.mock_debugger.var_manager.var_refs = {}
        self.mock_debugger.thread_tracker.frame_id_to_frame = {}
        self.mock_debugger.var_manager.next_var_ref = 1000

        # Mock frame
        self.mock_frame = Mock()
        self.mock_frame.f_locals = {"x": 10, "y": "hello"}
        self.mock_frame.f_globals = {"z": [1, 2, 3]}

        # Create mock state
        self.mock_state = SimpleNamespace(debugger=self.mock_debugger, is_terminated=False)

    def _set_object_member_direct(self, parent_obj, name, value):
        return command_handler_helpers.set_object_member(
            parent_obj,
            name,
            value,
            try_custom_convert=_try_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            convert_value_with_context_fn=convert_value_with_context,
            assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
            error_response_fn=command_handlers._error_response,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: self.mock_debugger,
            make_variable_fn=_make_variable_for_tests,
            logger=command_handlers.logger,
        )

    def _set_scope_variable_direct(self, frame, scope, name, value):
        return command_handler_helpers.set_scope_variable(
            frame,
            scope,
            name,
            value,
            try_custom_convert=_try_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            evaluate_with_policy_fn=command_handlers.evaluate_with_policy,
            convert_value_with_context_fn=convert_value_with_context,
            logger=command_handlers.logger,
            error_response_fn=command_handlers._error_response,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: self.mock_debugger,
            make_variable_fn=_make_variable_for_tests,
        )

    def _handle_set_variable(self, arguments):
        session = DebugSession()
        session.debugger = self.mock_debugger
        return variable_handlers.handle_set_variable_impl(
            session,
            arguments,
            error_response=command_handlers._error_response,
            set_object_member=self._set_object_member_direct,
            set_scope_variable=self._set_scope_variable_direct,
            logger=command_handlers.logger,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            var_ref_tuple_size=command_handlers.VAR_REF_TUPLE_SIZE,
        )

    def test_convert_string_to_value(self):
        """Test string to value conversion"""
        # Test basic types
        assert convert_value_with_context("None") is None
        assert convert_value_with_context("none") is None
        assert convert_value_with_context("True") is True
        assert convert_value_with_context("true") is True
        assert convert_value_with_context("False") is False
        assert convert_value_with_context("false") is False
        assert convert_value_with_context("42") == 42
        assert convert_value_with_context("3.14") == 3.14
        assert convert_value_with_context("'hello'") == "hello"
        assert convert_value_with_context("[1, 2, 3]") == [1, 2, 3]

    def test_create_variable_object_simple(self):
        """Test variable object creation for simple values"""
        # Test simple value
        var_obj = make_variable_object("test_var", 42)
        assert var_obj["name"] == "test_var"
        assert var_obj["value"] == "42"
        assert var_obj["type"] == "int"
        assert var_obj["variablesReference"] == 0

    def test_handle_set_variable_locals(self):
        """Test setting a local variable"""
        # Set up variable reference for locals
        frame_id = 1
        var_ref = 1001
        self.mock_debugger.var_manager.var_refs[var_ref] = (frame_id, "locals")
        self.mock_debugger.thread_tracker.frame_id_to_frame[frame_id] = self.mock_frame

        # Test arguments
        arguments = {"variablesReference": var_ref, "name": "x", "value": "99"}

        result = self._handle_set_variable(arguments)

        # Verify result
        assert result["success"]
        assert "body" in result
        assert result["body"]["value"] == "99"
        assert result["body"]["type"] == "int"

        # Verify variable was set
        assert self.mock_frame.f_locals["x"] == 99

    def test_handle_set_variable_globals(self):
        """Test setting a global variable"""
        # Set up variable reference for globals
        frame_id = 1
        var_ref = 1002
        self.mock_debugger.var_manager.var_refs[var_ref] = (frame_id, "globals")
        self.mock_debugger.thread_tracker.frame_id_to_frame[frame_id] = self.mock_frame

        # Test arguments
        arguments = {
            "variablesReference": var_ref,
            "name": "new_global",
            "value": "'test_string'",
        }

        # Call handler (pass debugger as first arg)
        result = self._handle_set_variable(arguments)

        # Verify result
        assert result["success"]
        assert result["body"]["value"] == "'test_string'"
        assert result["body"]["type"] == "str"

        # Verify variable was set
        assert self.mock_frame.f_globals["new_global"] == "test_string"

    def test_handle_set_variable_invalid_ref(self):
        """Test setting variable with invalid reference"""
        # Test arguments with invalid reference
        arguments = {"variablesReference": 9999, "name": "x", "value": "42"}

        # Call handler (pass debugger as first arg)
        result = self._handle_set_variable(arguments)

        # Verify error result
        assert not result["success"]
        assert "Invalid variable reference" in result["message"]


if __name__ == "__main__":
    unittest.main()
