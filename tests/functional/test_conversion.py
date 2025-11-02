"""
Test for the _convert_string_to_value function in debug_launcher.py
"""

from dapper.debug_launcher import _convert_string_to_value


def test_convert_string_to_value():
    """Test the string to value conversion function"""

    # Test None
    assert _convert_string_to_value("None") is None
    assert _convert_string_to_value("none") is None

    # Test booleans
    assert _convert_string_to_value("True") is True
    assert _convert_string_to_value("true") is True
    assert _convert_string_to_value("False") is False
    assert _convert_string_to_value("false") is False

    # Test integers
    assert _convert_string_to_value("42") == 42
    assert _convert_string_to_value("-10") == -10

    # Test floats
    assert _convert_string_to_value("3.14") == 3.14
    assert _convert_string_to_value("-2.5") == -2.5

    # Test strings
    assert _convert_string_to_value("'hello'") == "hello"
    assert _convert_string_to_value('"world"') == "world"

    # Test lists
    assert _convert_string_to_value("[1, 2, 3]") == [1, 2, 3]
    assert _convert_string_to_value("['a', 'b']") == ["a", "b"]

    # Test dicts
    assert _convert_string_to_value("{'a': 1}") == {"a": 1}

    # Test plain strings (fallback)
    assert _convert_string_to_value("plain_text") == "plain_text"
    assert _convert_string_to_value("invalid[syntax") == "invalid[syntax"

    # All tests passed - no print needed


if __name__ == "__main__":
    test_convert_string_to_value()