# Dapper AI Debug Adapter Tests

This directory contains unit tests for the Dapper AI Debug Adapter Protocol implementation.

## Running Tests

You can run the tests using either unittest directly or pytest:

```bash
# Using unittest
python -m unittest discover -s tests

# Using pytest
pytest
```

## Test Structure

- `test_protocol.py` - Tests for DAP message classes and serialization
- `test_connection.py` - Tests for connection handling (TCP and named pipes)
- `test_server.py` - Tests for the debug adapter server that processes requests

## Adding New Tests

When adding new tests:
1. Create a new test file with the prefix `test_` or add to an existing file
2. Write test methods with the prefix `test_` 
3. Use the standard unittest assertions for validation

## Mocking External Dependencies

The tests use unittest.mock to mock external dependencies like socket connections 
and filesystem operations. This keeps the tests fast and isolated.
