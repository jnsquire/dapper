"""

from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:


Test enhanced setVariable functionality
"""

import unittest
from unittest.mock import Mock

from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers
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


class TestEnhancedSetVariable(unittest.TestCase):
    """Test enhanced setVariable functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock debugger
        self.mock_debugger = Mock()
        self.mock_debugger.var_manager.var_refs = {}
        self.mock_debugger.thread_tracker.frame_id_to_frame = {}
        self.mock_debugger.var_manager.next_var_ref = 1000

        # Mock frame
        self.mock_frame = Mock()
        self.mock_frame.f_locals = {"x": 10, "items": [1, 2, 3]}
        self.mock_frame.f_globals = {"config": {"debug": True}}

    def _set_object_member_direct(self, parent_obj, name, value_str):
        return command_handler_helpers.set_object_member(
            parent_obj,
            name,
            value_str,
            try_custom_convert=_try_test_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            convert_value_with_context_fn=convert_value_with_context,
            assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
            error_response_fn=command_handlers._error_response,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: None,
            make_variable_fn=_make_variable_for_tests,
            logger=command_handlers.logger,
        )

    def _set_scope_variable_direct(self, frame, scope, name, value_str):
        return command_handler_helpers.set_scope_variable(
            frame,
            scope,
            name,
            value_str,
            try_custom_convert=_try_test_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            evaluate_with_policy_fn=command_handlers.evaluate_with_policy,
            convert_value_with_context_fn=convert_value_with_context,
            logger=command_handlers.logger,
            error_response_fn=command_handlers._error_response,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: None,
            make_variable_fn=_make_variable_for_tests,
        )

    def test_convert_value_with_context_expressions(self):
        """Test value conversion with frame context for expressions"""
        # Mock frame for expression evaluation
        frame = Mock()
        frame.f_locals = {"a": 5, "b": 10}
        frame.f_globals = {"math": __import__("math")}

        # Test simple expression
        result = convert_value_with_context("a + b", frame)
        assert result == 15

        # Test with global access
        result = convert_value_with_context("math.pi", frame)
        assert type(result) is float
        assert abs(result - 3.14159) < 0.001

    def test_convert_value_with_context_type_inference(self):
        """Test type inference based on parent object"""
        # Test list with numeric types
        parent_list = [1, 2, 3]
        result = convert_value_with_context("42", None, parent_list)
        assert result == 42
        assert isinstance(result, int)

        # Test dict with string values
        parent_dict = {"key1": "value1", "key2": "value2"}
        result = convert_value_with_context("new_value", None, parent_dict)
        assert result == "new_value"
        assert isinstance(result, str)

    def test_set_object_member_dict(self):
        """Test setting dictionary items"""
        test_dict = {"key1": "value1", "key2": "value2"}
        result = self._set_object_member_direct(test_dict, "key3", "'new_value'")

        assert result["success"]
        assert test_dict["key3"] == "new_value"
        assert result["body"]["value"] == "'new_value'"

    def test_set_object_member_list(self):
        """Test setting list items by index"""
        test_list = [1, 2, 3]
        result = self._set_object_member_direct(test_list, "1", "99")

        assert result["success"]
        assert test_list[1] == 99
        assert result["body"]["value"] == "99"

    def test_set_object_member_list_invalid_index(self):
        """Test setting list items with invalid index"""
        test_list = [1, 2, 3]
        result = self._set_object_member_direct(test_list, "10", "99")

        assert not result["success"]
        assert "out of range" in result["message"]

    def test_set_object_member_object_attribute(self):
        """Test setting object attributes"""

        class TestClass:
            def __init__(self):
                self.attr1 = "original"

        test_obj = TestClass()
        result = self._set_object_member_direct(test_obj, "attr1", "'modified'")

        assert result["success"]
        assert test_obj.attr1 == "modified"

    def test_set_object_member_tuple_immutable(self):
        """Test that tuples cannot be modified"""
        test_tuple = (1, 2, 3)
        result = self._set_object_member_direct(test_tuple, "0", "99")

        assert not result["success"]
        assert "immutable" in result["message"]

    def test_handle_set_variable_object_reference(self):
        """Test setVariable with object reference"""
        # Set up object reference
        test_dict = {"key": "value"}
        var_ref = 2001
        self.mock_debugger.var_manager.var_refs[var_ref] = ("object", test_dict)

        arguments = {
            "variablesReference": var_ref,
            "name": "new_key",
            "value": "'new_value'",
        }

        result = variable_handlers.handle_set_variable_impl(
            self.mock_debugger,
            arguments,
            error_response=command_handlers._error_response,
            set_object_member=self._set_object_member_direct,
            set_scope_variable=self._set_scope_variable_direct,
            logger=command_handlers.logger,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            var_ref_tuple_size=command_handlers.VAR_REF_TUPLE_SIZE,
        )

        assert result["success"]
        assert test_dict["new_key"] == "new_value"

    def test_handle_set_variable_scope_with_expression(self):
        """Test setVariable with expression evaluation in scope"""
        # Set up frame with variables for expression
        frame_id = 1
        var_ref = 1001
        self.mock_frame.f_locals = {"a": 5, "b": 10}
        self.mock_debugger.var_manager.var_refs[var_ref] = (frame_id, "locals")
        self.mock_debugger.thread_tracker.frame_id_to_frame[frame_id] = self.mock_frame

        result = self._set_scope_variable_direct(self.mock_frame, "locals", "result", "a * b")

        assert result["success"]
        assert self.mock_frame.f_locals["result"] == 50


if __name__ == "__main__":
    unittest.main()
