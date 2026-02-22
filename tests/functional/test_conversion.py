"""Test for the _convert_string_to_value function in debug_launcher.py"""

from dapper.shared.value_conversion import convert_value_with_context


def test_convert_string_to_value():
    """Test the string to value conversion function"""
    # Test None
    assert convert_value_with_context("None") is None
    assert convert_value_with_context("none") is None

    # Test booleans
    assert convert_value_with_context("True") is True
    assert convert_value_with_context("true") is True
    assert convert_value_with_context("False") is False
    assert convert_value_with_context("false") is False

    # Test integers
    assert convert_value_with_context("42") == 42
    assert convert_value_with_context("-10") == -10

    # Test floats
    assert convert_value_with_context("3.14") == 3.14
    assert convert_value_with_context("-2.5") == -2.5

    # Test strings
    assert convert_value_with_context("'hello'") == "hello"
    assert convert_value_with_context('"world"') == "world"

    # Test lists
    assert convert_value_with_context("[1, 2, 3]") == [1, 2, 3]
    assert convert_value_with_context("['a', 'b']") == ["a", "b"]

    # Test dicts
    assert convert_value_with_context("{'a': 1}") == {"a": 1}

    # Test plain strings (fallback)
    assert convert_value_with_context("plain_text") == "plain_text"
    assert convert_value_with_context("invalid[syntax") == "invalid[syntax"

    # All tests passed - no print needed


if __name__ == "__main__":
    test_convert_string_to_value()
