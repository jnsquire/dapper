"""

from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:


Test enhanced setVariable functionality
"""

import unittest
from unittest.mock import Mock
from unittest.mock import patch

from dapper.shared.launcher_handlers import _convert_value_with_context
from dapper.shared.launcher_handlers import _set_object_member
from dapper.shared.launcher_handlers import _set_scope_variable
from dapper.shared.launcher_handlers import handle_set_variable


class TestEnhancedSetVariable(unittest.TestCase):
    """Test enhanced setVariable functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock debugger
        self.mock_debugger = Mock()
        self.mock_debugger.var_refs = {}
        self.mock_debugger.frame_id_to_frame = {}
        self.mock_debugger.next_var_ref = 1000

        # Mock frame
        self.mock_frame = Mock()
        self.mock_frame.f_locals = {"x": 10, "items": [1, 2, 3]}
        self.mock_frame.f_globals = {"config": {"debug": True}}

    def test_convert_value_with_context_expressions(self):
        """Test value conversion with frame context for expressions"""
        # Mock frame for expression evaluation
        frame = Mock()
        frame.f_locals = {"a": 5, "b": 10}
        frame.f_globals = {"math": __import__("math")}

        # Test simple expression
        result = _convert_value_with_context("a + b", frame)
        assert result == 15

        # Test with global access
        result = _convert_value_with_context("math.pi", frame)
        assert type(result) is float
        assert abs(result - 3.14159) < 0.001

    def test_convert_value_with_context_type_inference(self):
        """Test type inference based on parent object"""
        # Test list with numeric types
        parent_list = [1, 2, 3]
        result = _convert_value_with_context("42", None, parent_list)
        assert result == 42
        assert isinstance(result, int)

        # Test dict with string values
        parent_dict = {"key1": "value1", "key2": "value2"}
        result = _convert_value_with_context("new_value", None, parent_dict)
        assert result == "new_value"
        assert isinstance(result, str)

    @patch("dapper.launcher.debug_launcher.state")
    def test_set_object_member_dict(self, mock_state):
        """Test setting dictionary items"""
        mock_state.debugger = self.mock_debugger

        test_dict = {"key1": "value1", "key2": "value2"}
        result = _set_object_member(test_dict, "key3", "'new_value'")

        assert result["success"]
        assert test_dict["key3"] == "new_value"
        assert result["body"]["value"] == "'new_value'"

    @patch("dapper.launcher.debug_launcher.state")
    def test_set_object_member_list(self, mock_state):
        """Test setting list items by index"""
        mock_state.debugger = self.mock_debugger

        test_list = [1, 2, 3]
        result = _set_object_member(test_list, "1", "99")

        assert result["success"]
        assert test_list[1] == 99
        assert result["body"]["value"] == "99"

    @patch("dapper.launcher.debug_launcher.state")
    def test_set_object_member_list_invalid_index(self, mock_state):
        """Test setting list items with invalid index"""
        mock_state.debugger = self.mock_debugger

        test_list = [1, 2, 3]
        result = _set_object_member(test_list, "10", "99")

        assert not result["success"]
        assert "out of range" in result["message"]

    @patch("dapper.launcher.debug_launcher.state")
    def test_set_object_member_object_attribute(self, mock_state):
        """Test setting object attributes"""
        mock_state.debugger = self.mock_debugger

        class TestClass:
            def __init__(self):
                self.attr1 = "original"

        test_obj = TestClass()
        result = _set_object_member(test_obj, "attr1", "'modified'")

        assert result["success"]
        assert test_obj.attr1 == "modified"

    @patch("dapper.launcher.debug_launcher.state")
    def test_set_object_member_tuple_immutable(self, mock_state):
        """Test that tuples cannot be modified"""
        mock_state.debugger = self.mock_debugger

        test_tuple = (1, 2, 3)
        result = _set_object_member(test_tuple, "0", "99")

        assert not result["success"]
        assert "immutable" in result["message"]

    @patch("dapper.launcher.debug_launcher.state")
    def test_handle_set_variable_object_reference(self, mock_state):
        """Test setVariable with object reference"""
        mock_state.debugger = self.mock_debugger

        # Set up object reference
        test_dict = {"key": "value"}
        var_ref = 2001
        self.mock_debugger.var_refs[var_ref] = ("object", test_dict)

        arguments = {
            "variablesReference": var_ref,
            "name": "new_key",
            "value": "'new_value'",
        }

        result = handle_set_variable(self.mock_debugger, arguments)

        assert result["success"]
        assert test_dict["new_key"] == "new_value"

    @patch("dapper.launcher.debug_launcher.state")
    def test_handle_set_variable_scope_with_expression(self, mock_state):
        """Test setVariable with expression evaluation in scope"""
        mock_state.debugger = self.mock_debugger

        # Set up frame with variables for expression
        frame_id = 1
        var_ref = 1001
        self.mock_frame.f_locals = {"a": 5, "b": 10}
        self.mock_debugger.var_refs[var_ref] = (frame_id, "locals")
        self.mock_debugger.frame_id_to_frame[frame_id] = self.mock_frame

        result = _set_scope_variable(self.mock_frame, "locals", "result", "a * b")

        assert result["success"]
        assert self.mock_frame.f_locals["result"] == 50


if __name__ == "__main__":
    unittest.main()
