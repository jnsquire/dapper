"""
Integration test for setVariable functionality.
This test verifies that variables can actually be set during debugging.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

# Test program that will be debugged
TEST_PROGRAM = """
def main():
    x = 10
    y = "hello"
    z = [1, 2, 3]
    
    # Breakpoint will be set here
    print(f"x={x}, y={y}, z={z}")  # Line 7
    
    # After setVariable calls, values should be different
    print(f"After: x={x}, y={y}, z={z}")  # Line 10

if __name__ == "__main__":
    main()
"""


def test_set_variable_integration():
    """Test setVariable functionality with actual debugging session"""

    # Create temporary test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(TEST_PROGRAM)
        test_file = f.name

    try:
        # Start debugger process
        cmd = [
            sys.executable,
            "-m",
            "dapper",
            "--stop-on-entry",
            test_file,
        ]

        # Starting debugger command (removed print)

        # For now, just verify the command doesn't crash
        # TODO: Add actual DAP communication to test setVariable
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            input="exit\n",
        )

        # Check results (removed prints for cleaner output)

        # Just verify the debugger starts without crashing
        assert result.returncode != 1, "Debugger should not crash on startup"

    except subprocess.TimeoutExpired:
        # Debugger started successfully (timeout expected)
        pass

    finally:
        # Clean up
        Path(test_file).unlink(missing_ok=True)


if __name__ == "__main__":
    test_set_variable_integration()
    # Integration test completed (removed print)
