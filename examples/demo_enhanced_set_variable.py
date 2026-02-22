"""
Demo for enhanced setVariable functionality in Dapper debugger.

This demo shows how to:
1. Set variables in scope (locals/globals)
2. Set object attributes
3. Set list elements
4. Set dictionary values
5. Use expressions for variable values
6. Handle type conversions

When debugging this script, you can use setVariable to modify:
- Simple variables (strings, numbers, booleans)
- Object attributes
- List elements by index
- Dictionary keys
- Complex expressions
"""


class Person:
    """Demo class for object attribute setting"""

    def __init__(self, name, age):
        self.name = name
        self.age = age
        self.metadata = {}

    def __repr__(self):
        return f"Person(name='{self.name}', age={self.age})"


def demo_enhanced_set_variable():
    """Demo function showing various setVariable scenarios"""
    # Variables that can be modified via setVariable
    name = "Alice"
    age = 30
    is_active = True

    # Objects for attribute setting
    person = Person("Bob", 25)

    # Collections for element setting
    numbers = [1, 2, 3, 4, 5]
    user_data = {
        "username": "admin",
        "role": "user",
        "settings": {"theme": "dark", "notifications": True},
    }

    # Complex data structure
    company = {
        "name": "TechCorp",
        "employees": [Person("Charlie", 28), Person("Diana", 32)],
        "departments": ["Engineering", "Sales", "HR"],
    }

    print("=== Enhanced setVariable Demo ===")
    print("Initial state:")
    print(f"  name: {name}")
    print(f"  age: {age}")
    print(f"  is_active: {is_active}")
    print(f"  person: {person}")
    print(f"  numbers: {numbers}")
    print(f"  user_data: {user_data}")
    print(f"  company: {company}")

    # Set a breakpoint here and try these setVariable operations:

    # 1. Simple variable modifications:
    #    - name = "Alice Updated"
    #    - age = 31
    #    - is_active = False

    # 2. Object attribute modifications:
    #    - person.name = "Bob Updated"
    #    - person.age = 26
    #    - person.metadata['last_login'] = "2024-01-15"

    # 3. List element modifications:
    #    - numbers[0] = 100
    #    - numbers[2] = 300

    # 4. Dictionary modifications:
    #    - user_data['username'] = "superadmin"
    #    - user_data['settings']['theme'] = "light"

    # 5. Expression-based modifications:
    #    - age = age + 1
    #    - numbers[1] = numbers[0] + numbers[2]

    print("\n=== After modifications (if any) ===")
    print(f"  name: {name}")
    print(f"  age: {age}")
    print(f"  is_active: {is_active}")
    print(f"  person: {person}")
    print(f"  numbers: {numbers}")
    print(f"  user_data: {user_data}")
    print(f"  company: {company}")


def test_type_conversions():
    """Test automatic type conversions"""
    # String values
    text = "hello"

    # Numeric values
    count = 42
    price = 19.99

    # Boolean values
    enabled = True

    # List with mixed types
    mixed_list = [1, "two", 3.0, True]

    # Dictionary with mixed types
    config = {
        "port": 8080,
        "host": "localhost",
        "debug": False,
        "timeout": 30.5,
    }

    print("=== Type Conversion Demo ===")
    print("Initial values:")
    print(f"  text: {text} ({type(text).__name__})")
    print(f"  count: {count} ({type(count).__name__})")
    print(f"  price: {price} ({type(price).__name__})")
    print(f"  enabled: {enabled} ({type(enabled).__name__})")
    print(f"  mixed_list: {mixed_list}")
    print(f"  config: {config}")

    # Test type conversions by setting variables:
    # - text = 123 (str -> int)
    # - count = "456" (int -> str, but will convert to int)
    # - price = "29.99" (float -> str, but will convert to float)
    # - enabled = "false" (bool -> str, but will convert to bool)
    # - mixed_list[1] = 2 (string element to int)
    # - config['port'] = "9000" (will convert to int based on existing type)

    print("\nAfter modifications:")
    print(f"  text: {text} ({type(text).__name__})")
    print(f"  count: {count} ({type(count).__name__})")
    print(f"  price: {price} ({type(price).__name__})")
    print(f"  enabled: {enabled} ({type(enabled).__name__})")
    print(f"  mixed_list: {mixed_list}")
    print(f"  config: {config}")


if __name__ == "__main__":
    print("Starting enhanced setVariable demo...")
    print("This demo shows the enhanced capabilities of the setVariable feature.")
    print("Set breakpoints and use your debugger's setVariable functionality to modify variables.")
    print()

    demo_enhanced_set_variable()
    print()
    test_type_conversions()

    print("\nDemo complete!")
