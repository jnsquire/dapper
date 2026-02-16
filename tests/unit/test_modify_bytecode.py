"""Unit tests for the modify_bytecode module."""

import types
from unittest import TestCase
from unittest import mock

from dapper._frame_eval import modify_bytecode as mb
from dapper._frame_eval.modify_bytecode import _bytecode_modifier
from dapper._frame_eval.modify_bytecode import insert_code


def make_simple_code():
    src = """
def foo():
    x = 1
    y = x + 2
    return y
"""
    compiled = compile(src, "<test_mod>", "exec")
    # Extract the code object for foo
    for const in compiled.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "foo":
            return const
    raise RuntimeError("could not find foo code object")


def test_create_breakpoint_instruction_length_and_opcode():
    data = mb.create_breakpoint_instruction(10)
    # Should be bytes and non-empty
    assert isinstance(data, (bytes, bytearray))
    # Expected layout: LOAD_CONST (1+2), CALL_FUNCTION (1+2), POP_TOP (1) => 7 bytes
    assert len(data) == 7
    # First opcode byte should equal module's LOAD_CONST
    assert data[0] == mb.LOAD_CONST


def test_validate_and_info():
    code = make_simple_code()
    assert mb.validate_bytecode(code) is True
    info = mb.get_bytecode_info(code)
    assert info["instruction_count"] > 0
    assert info["name"] == "foo"
    assert "filename" in info


def test_insert_code_negative_line_returns_false():
    code = make_simple_code()
    success, modified = mb.insert_code(code, -1, ())
    assert success is False
    assert modified is code


def test_inject_and_remove_noop_and_cache_and_flags():
    code = make_simple_code()
    # Clear cache first
    mb.clear_bytecode_cache()
    stats_before = mb.get_cache_stats()
    assert stats_before["cached_code_objects"] == 0

    # Inject with empty set should be a no-op success
    ok, new_code = mb.inject_breakpoint_bytecode(code, set())
    assert ok is True
    assert new_code is code

    # Remove should also return a code object
    cleaned = mb.remove_breakpoint_bytecode(code)
    assert isinstance(cleaned, types.CodeType)

    # Toggle optimization flag
    mb.set_optimization_enabled(False)
    stats = mb.get_cache_stats()
    assert stats["optimization_enabled"] is False
    mb.set_optimization_enabled(True)


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

    def tearDown(self):
        """Ensure any active patches are stopped to avoid leaking mocks."""
        mock.patch.stopall()

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
