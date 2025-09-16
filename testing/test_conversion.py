"""
Test for the _convert_string_to_value function in debug_launcher.py
"""

import sys
from pathlib import Path

# Try to import from the installed package first; if that fails (for local
# development runs), add the repo root to sys.path and import the module.
try:
    from dapper.debug_launcher import _convert_string_to_value
except Exception:
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
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
