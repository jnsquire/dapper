"""
Manual Test Example for Set Variable Feature

This example demonstrates the newly implemented setVariable functionality
in the Dapper AI debugger.

To test manually:
1. Set a breakpoint on line 20 (the print statement)
2. Start debugging this script
3. When execution stops, examine variables x, y, z
4. Use the debugger's setVariable functionality to change their values
5. Continue execution to see the changed values
"""


def demo_set_variable():
    """Demonstrate variable modification during debugging"""

    # Initialize some variables with different types
    x = 42  # Integer
    y = "original_string"  # String
    z = [1, 2, 3]  # List
    pi = 3.14159  # Float
    flag = True  # Boolean
    data = {"key": "value"}  # Dictionary

    # Breakpoint should be set here - examine and modify variables
    print("Before modification:")
    print(f"  x = {x} (type: {type(x).__name__})")
    print(f"  y = {y} (type: {type(y).__name__})")
    print(f"  z = {z} (type: {type(z).__name__})")
    print(f"  pi = {pi} (type: {type(pi).__name__})")
    print(f"  flag = {flag} (type: {type(flag).__name__})")
    print(f"  data = {data} (type: {type(data).__name__})")

    # The variables should now reflect any changes made during debugging
    print("\nAfter potential modification:")
    print(f"  x = {x} (type: {type(x).__name__})")
    print(f"  y = {y} (type: {type(y).__name__})")
    print(f"  z = {z} (type: {type(z).__name__})")
    print(f"  pi = {pi} (type: {type(pi).__name__})")
    print(f"  flag = {flag} (type: {type(flag).__name__})")
    print(f"  data = {data} (type: {type(data).__name__})")


def test_global_variables():
    """Test setting global variables"""
    # Assign via globals() to avoid using the `global` statement which is
    # discouraged by linters in examples.
    globals()["GLOBAL_VAR"] = "initial_global_value"

    # Set breakpoint here to modify GLOBAL_VAR
    print(f"Global variable: {GLOBAL_VAR}")


# Global variable for testing
GLOBAL_VAR = "unmodified"


if __name__ == "__main__":
    print("=== Set Variable Demo ===")
    print("1. Testing local variables...")
    demo_set_variable()

    print("\n2. Testing global variables...")
    test_global_variables()

    print("\n=== Demo Complete ===")
    print("\nSuggested setVariable test cases:")
    print("- Change x to 999")
    print("- Change y to 'modified_string'")
    print("- Change z to [4, 5, 6]")
    print("- Change pi to 2.718")
    print("- Change flag to False")
    print("- Change data to {'new': 'data'}")
    print("- Change GLOBAL_VAR to 'modified_global'")
