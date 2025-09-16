# Dapper Debug Adapter Testing

This directory contains all testing utilities for the Dapper debug adapter.

## Quick Start

Use the streamlined test runner:

```bash
# Run setup verification tests
python testing/test_runner.py setup

# Start debug adapter and test connection
python testing/test_runner.py full

# Show manual testing instructions  
python testing/test_runner.py manual
```

## Test Runner Commands

| Command | Description |
|---------|-------------|
| `setup` | Run setup verification tests |
| `start` | Start debug adapter (interactive) |
| `connect` | Test connection to running adapter |
| `debug` | Run debug session (requires running adapter) |
| `manual` | Show manual testing instructions |
| `full` | Full automated test (start → connect → debug → stop) |

## Files

- **`test_runner.py`** - Main test runner with streamlined interface
- **`test_debug_adapter_setup.py`** - Setup verification tests
- **`test_dapper_client.py`** - DAP client for testing protocol communication
- **`test_setup.bat`** - Windows batch script (legacy)
- **`test_setup.ps1`** - PowerShell script (legacy)
- **`test_dapper_manual.bat`** - Manual testing helper (legacy)
- **`test_two_terminals.bat`** - Two-terminal setup helper (legacy)

## Examples

### Quick Verification
```bash
python testing/test_runner.py setup
```

### Full Automated Test
```bash
python testing/test_runner.py full
```

### Manual Testing
```bash
# Terminal 1
python testing/test_runner.py start

# Terminal 2  
python testing/test_runner.py connect
python testing/test_runner.py debug
```

### Test Different Program
```bash
python testing/test_runner.py debug --program examples/sample_programs/advanced_app.py
```

### Use Different Port
```bash
python testing/test_runner.py full --port 5555
```

## VS Code Integration

The main project's `.vscode/launch.json` contains configurations that work with these test scripts:

- **"Launch Debug Adapter (TCP)"** - Start your adapter
- **"Test Dapper Debug Adapter"** - Run DAP client test

Paths in VS Code configurations have been updated to reference `testing/` directory.
