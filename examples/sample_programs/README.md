# Debug Adapter Testing Setup

This directory contains example code and configurations for testing the Dapper debug adapter with VS Code.

## Files Overview

### Example Programs

- **`sample_programs/simple_app.py`** - Basic Python application with common debugging scenarios:
  - Variable inspection
  - Function calls
  - List processing
  - Exception handling
  - Basic loops and conditionals

- **`sample_programs/advanced_app.py`** - Advanced Python application with complex scenarios:
  - Classes and dataclasses
  - Async/await functionality
  - Generators
  - Multi-threading
  - Complex data structures
  - Custom exceptions

### Test Scripts

- **`testing/test_debug_adapter_setup.py`** - Automated test script to verify the debug adapter setup

### VS Code Configuration

- **`.vscode/launch.json`** - Launch configurations for debugging with VS Code

## Quick Start Guide

### 1. Prerequisites

Make sure you have the development environment set up:

```bash
# Install development dependencies
uv pip install -e ".[dev]"
```

### 2. Test the Setup

Run the automated test script to verify everything is working:

```bash
python testing/test_debug_adapter_setup.py
```

This will test:
- VS Code configuration validity
- Example program execution
- Debug adapter launch capability

### 3. Manual Testing with VS Code

#### Option A: Launch Debug Adapter First

1. **Start the debug adapter** using VS Code:
   - Open the Run and Debug panel (Ctrl+Shift+D)
   - Select "Launch Debug Adapter (TCP)"
   - Click the green play button
   - The adapter will start listening on port 4711

2. **Debug an example program**:
   - In another VS Code window, open the project
   - Set breakpoints in `examples/sample_programs/simple_app.py`
   - Use a VS Code extension or external client to connect to the debug adapter

#### Option B: Use Standard Python Debugging for Comparison

1. **Debug with standard Python debugger**:
   - Select "Debug Simple App (Standard Python)" or "Debug Advanced App (Standard Python)"
   - Set breakpoints and step through the code
   - Compare behavior with your debug adapter

### 4. Testing Scenarios

#### Basic Debugging Features

Test these features in `simple_app.py`:

1. **Breakpoints**:
   - Set breakpoints on lines 67, 72, 89
   - Verify breakpoints are hit during execution

2. **Variable Inspection**:
   - Inspect `test_numbers`, `stats`, `fib_result`
   - Check nested data structures

3. **Step Operations**:
   - Step into `calculate_fibonacci()`
   - Step over `process_numbers()`
   - Step out of functions

4. **Exception Handling**:
   - Set breakpoint in `demonstrate_exception_handling()`
   - Step through try/catch block

#### Advanced Debugging Features

Test these features in `advanced_app.py`:

1. **Object Inspection**:
   - Inspect `Person` dataclass instances
   - Check `DataProcessor` object state

2. **Async Debugging**:
   - Debug `async_data_fetcher()` function
   - Step through `await` statements

3. **Threading**:
   - Set breakpoints in `threaded_worker()`
   - Observe multiple thread execution

4. **Generators**:
   - Debug the `process_numbers()` generator
   - Step through `yield` statements

## Launch Configurations Explained

### Debug Adapter Configurations

- **"Launch Debug Adapter (TCP)"** - Starts the adapter on TCP port 4711
- **"Launch Debug Adapter (Named Pipe)"** - Starts the adapter with named pipe communication

### Example Program Configurations

- **"Debug Simple App (Standard Python)"** - Debug simple_app.py with VS Code's built-in Python debugger
- **"Debug Advanced App (Standard Python)"** - Debug advanced_app.py with VS Code's built-in Python debugger

### Test Configuration

- **"Run Tests with Debug"** - Run the test suite with debugging enabled

## Debugging the Debug Adapter

If you need to debug the debug adapter itself:

1. **Set breakpoints** in the adapter code (e.g., `dapper/adapter.py`, `dapper/server.py`)
2. **Launch with debugging** using "Launch Debug Adapter (TCP)" configuration
3. **Connect a client** to trigger the adapter code

## Common Issues and Solutions

### Port Already in Use

If you get "port already in use" error:

```bash
# Check what's using the port
netstat -an | findstr 4711

# Kill existing processes if needed
taskkill /F /PID <process_id>
```

### Example Programs Not Running

If example programs fail:

1. Check Python environment is activated
2. Verify all dependencies are installed: `uv pip install -e ".[dev]"`
3. Run the test script: `python testing/test_debug_adapter_setup.py`

### VS Code Not Connecting to Adapter

1. Ensure the debug adapter is running and listening
2. Check the port number matches (default: 4711)
3. Verify no firewall is blocking the connection
4. Check the adapter logs for error messages

## Extending the Examples

To add new test scenarios:

1. **Create new example programs** in `sample_programs/`
2. **Add launch configurations** in `.vscode/launch.json`
3. **Update the test script** to include new programs
4. **Document new debugging scenarios** in this README

## Tips for Effective Testing

1. **Start simple** - Use `simple_app.py` first to verify basic functionality
2. **Use logging** - Enable DEBUG logging to see detailed adapter communication
3. **Test incrementally** - Add one debugging feature at a time
4. **Compare behavior** - Use the standard Python debugger as a reference
5. **Document issues** - Keep notes on any problems for debugging the adapter

## Protocol Testing

For testing the Debug Adapter Protocol communication:

1. **Enable verbose logging** with `--log-level DEBUG`
2. **Monitor network traffic** to see DAP messages
3. **Use protocol documentation** from `doc/debugAdapterProtocol.json`
4. **Test edge cases** like invalid requests, connection drops, etc.

This setup provides a comprehensive testing environment for developing and verifying your debug adapter implementation.
