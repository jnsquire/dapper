"""Unit tests for the modify_bytecode module."""

from unittest import TestCase
from unittest import mock

from dapper._frame_eval.modify_bytecode import _bytecode_modifier
from dapper._frame_eval.modify_bytecode import insert_code


class TestInsertCode(TestCase):
    """Test the insert_code function."""

    def setUp(self):
        """Set up test fixtures."""

        # Create a simple code object for testing
        def test_func():
            x = 1
            y = 2
            return x + y

        self.test_code = test_func.__code__
        self.breakpoint_lines = (2, 3)  # Lines where to insert breakpoints

    def test_insert_code_success(self):
        """Test successful insertion of breakpoints."""
        # Mock the bytecode modifier to return a modified code object
        mock_modified_code = mock.MagicMock()
        mock_inject = mock.MagicMock()
        mock.patch.object(_bytecode_modifier, "inject_breakpoints", mock_inject).start()
        mock_inject.return_value = (True, mock_modified_code)

        success, result = insert_code(self.test_code, 2, self.breakpoint_lines)

        assert success
        assert result is mock_modified_code
        mock_inject.assert_called_once_with(
            self.test_code, set(self.breakpoint_lines), debug_mode=True
        )

    def test_insert_code_failure(self):
        """Test handling of exceptions during breakpoint insertion."""
        mock_inject = mock.MagicMock()
        mock.patch.object(_bytecode_modifier, "inject_breakpoints", mock_inject).start()
        mock_inject.side_effect = Exception("Test error")

        success, result = insert_code(self.test_code, 2, self.breakpoint_lines)

        assert not success
        assert result is self.test_code

    def test_insert_code_returns_original_on_error(self):
        """Test that the original code object is returned on error."""
        mock_inject = mock.MagicMock()
        mock.patch.object(_bytecode_modifier, "inject_breakpoints", mock_inject).start()
        mock_inject.side_effect = Exception("Test error")

        success, result = insert_code(self.test_code, 2, self.breakpoint_lines)

        assert not success
        assert result == self.test_code

    def test_insert_code_with_empty_breakpoints(self):
        """Test with empty breakpoint lines."""
        mock_modified_code = mock.MagicMock()
        mock_inject = mock.MagicMock()
        mock.patch.object(_bytecode_modifier, "inject_breakpoints", mock_inject).start()
        mock_inject.return_value = (True, mock_modified_code)

        success, _ = insert_code(
            self.test_code,
            2,
            (),  # Empty breakpoint lines
        )

        assert success
        mock_inject.assert_called_once()
        assert mock_inject.call_args[0][1] == set()  # Should be an empty set

    def test_insert_code_with_invalid_line_number(self):
        """Test with an invalid line number (negative)."""
        success, result = insert_code(
            self.test_code,
            -1,  # Invalid line number
            self.breakpoint_lines,
        )

        # Should still return successfully but with original code object
        assert not success
        assert result == self.test_code


if __name__ == "__main__":
    import unittest

    unittest.main()
