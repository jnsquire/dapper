"""

Test for setVariable functionality in debug_launcher.py
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

# Import the specific functions we want to test
from dapper.shared.debug_shared import make_variable_object
from dapper.shared.launcher_handlers import _convert_string_to_value
from dapper.shared.launcher_handlers import handle_set_variable


class TestSetVariable(unittest.TestCase):
    """Test setVariable functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock debugger
        self.mock_debugger = Mock()
        self.mock_debugger.var_refs = {}
        self.mock_debugger.frame_id_to_frame = {}
        self.mock_debugger.next_var_ref = 1000

        # Mock frame
        self.mock_frame = Mock()
        self.mock_frame.f_locals = {"x": 10, "y": "hello"}
        self.mock_frame.f_globals = {"z": [1, 2, 3]}

        # Create mock state
        self.mock_state = SimpleNamespace(debugger=self.mock_debugger, is_terminated=False)

    def test_convert_string_to_value(self):
        """Test string to value conversion"""
        # Test basic types
        assert _convert_string_to_value("None") is None
        assert _convert_string_to_value("none") is None
        assert _convert_string_to_value("True") is True
        assert _convert_string_to_value("true") is True
        assert _convert_string_to_value("False") is False
        assert _convert_string_to_value("false") is False
        assert _convert_string_to_value("42") == 42
        assert _convert_string_to_value("3.14") == 3.14
        assert _convert_string_to_value("'hello'") == "hello"
        assert _convert_string_to_value("[1, 2, 3]") == [1, 2, 3]

    @patch("dapper.launcher.debug_launcher.state")
    def test_create_variable_object_simple(self, mock_state):
        """Test variable object creation for simple values"""
        mock_state.debugger = self.mock_debugger

        # Test simple value
        var_obj = make_variable_object("test_var", 42)
        assert var_obj["name"] == "test_var"
        assert var_obj["value"] == "42"
        assert var_obj["type"] == "int"
        assert var_obj["variablesReference"] == 0

    @patch("dapper.launcher.debug_launcher.state")
    def test_handle_set_variable_locals(self, mock_state):
        """Test setting a local variable"""
        # Set up mocks
        mock_state.debugger = self.mock_debugger

        # Set up variable reference for locals
        frame_id = 1
        var_ref = 1001
        self.mock_debugger.var_refs[var_ref] = (frame_id, "locals")
        self.mock_debugger.frame_id_to_frame[frame_id] = self.mock_frame

        # Test arguments
        arguments = {"variablesReference": var_ref, "name": "x", "value": "99"}

        result = handle_set_variable(self.mock_debugger, arguments)

        # Verify result
        assert result["success"]
        assert "body" in result
        assert result["body"]["value"] == "99"
        assert result["body"]["type"] == "int"

        # Verify variable was set
        assert self.mock_frame.f_locals["x"] == 99

    @patch("dapper.launcher.debug_launcher.state")
    def test_handle_set_variable_globals(self, mock_state):
        """Test setting a global variable"""
        # Set up mocks
        mock_state.debugger = self.mock_debugger

        # Set up variable reference for globals
        frame_id = 1
        var_ref = 1002
        self.mock_debugger.var_refs[var_ref] = (frame_id, "globals")
        self.mock_debugger.frame_id_to_frame[frame_id] = self.mock_frame

        # Test arguments
        arguments = {
            "variablesReference": var_ref,
            "name": "new_global",
            "value": "'test_string'",
        }

        # Call handler (pass debugger as first arg)
        result = handle_set_variable(self.mock_debugger, arguments)

        # Verify result
        assert result["success"]
        assert result["body"]["value"] == "'test_string'"
        assert result["body"]["type"] == "str"

        # Verify variable was set
        assert self.mock_frame.f_globals["new_global"] == "test_string"

    @patch("dapper.launcher.debug_launcher.state")
    def test_handle_set_variable_invalid_ref(self, mock_state):
        """Test setting variable with invalid reference"""
        # Set up mocks
        mock_state.debugger = self.mock_debugger

        # Test arguments with invalid reference
        arguments = {"variablesReference": 9999, "name": "x", "value": "42"}

        # Call handler (pass debugger as first arg)
        result = handle_set_variable(self.mock_debugger, arguments)

        # Verify error result
        assert not result["success"]
        assert "Invalid variable reference" in result["message"]


if __name__ == "__main__":
    unittest.main()
