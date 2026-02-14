# Error Handling Guide for Dapper Debug Adapter

This guide outlines the standardized error handling patterns used across the Dapper debug adapter codebase.

## Overview

Dapper uses a hierarchical error handling system with:
- **Specific exception types** for different error categories
- **Standardized decorators** for consistent error wrapping and logging
- **Context managers** for temporary error handling scenarios
- **Centralized error response creation** for DAP protocol responses

## Error Hierarchy

### Base Exception
- `DapperError` - Base class for all Dapper-specific exceptions

### Specific Error Types
- `ConfigurationError` - Configuration-related errors
- `IPCError` - IPC transport and communication errors  
- `DebuggerError` - Debugger operation errors
- `ProtocolError` - DAP protocol errors
- `BackendError` - Backend operation errors
- `DapperTimeoutError` - Timeout-related errors

## Standardized Decorators

### Adapter Layer Error Handling

Use `@async_handle_adapter_errors()` for adapter request handlers:

```python
from dapper.errors import async_handle_adapter_errors

@async_handle_adapter_errors("attach")
async def _handle_attach(self, request: AttachRequest) -> AttachResponse:
    """Handle attach request."""
    config = DapperConfig.from_attach_request(request)
    config.validate()
    
    await self.server.debugger.attach(**config.to_attach_kwargs())
    
    return {
        "seq": 0,
        "type": "response", 
        "request_seq": request["seq"],
        "success": True,
        "command": "attach",
    }
```

### Backend Layer Error Handling

Use `@async_handle_backend_errors()` for backend operations:

```python
from dapper.errors import async_handle_backend_errors

@async_handle_backend_errors("inprocess", "evaluate")
async def evaluate(
    self,
    expression: str,
    frame_id: int | None = None,
    context: str | None = None,
) -> EvaluateResponseBody:
    """Evaluate an expression."""
    # Implementation here
    pass
```

### Debugger Operation Error Handling

Use `@async_handle_debugger_errors()` for debugger operations:

```python
from dapper.errors import async_handle_debugger_errors

@async_handle_debugger_errors("set_breakpoint", thread_id=1)
async def set_breakpoint(self, file: str, line: int) -> Breakpoint:
    """Set a breakpoint."""
    # Implementation here
    pass
```

### Protocol Layer Error Handling

Use `@handle_protocol_errors()` for protocol command processing:

```python
from dapper.errors import handle_protocol_errors

@handle_protocol_errors(command="setBreakpoints", sequence=123)
def process_set_breakpoints(self, request: dict) -> dict:
    """Process setBreakpoints command."""
    # Implementation here
    pass
```

## Context Manager Pattern

For temporary error handling scenarios, use the `ErrorContext` context manager:

```python
from dapper.errors import ErrorContext, IPCError

async def connect_to_debuggee(self, endpoint: str):
    """Connect to debuggee with standardized error handling."""
    async with ErrorContext("connect_to_debuggee", IPCError, endpoint=endpoint):
        # Connection logic here
        pass
```

## Error Response Creation

For DAP protocol error responses, use the centralized `create_dap_response` function:

```python
from dapper.errors import create_dap_response, IPCError

try:
    # Some operation that might fail
    pass
except IPCError as e:
    return create_dap_response(e, request["seq"], "attach")
```

## Best Practices

### 1. Use Specific Error Types
Always use the most specific error type for your situation:

```python
# Good
raise IPCError("Failed to connect to debuggee", transport="tcp", endpoint="localhost:5678")

# Avoid
raise Exception("Connection failed")
```

### 2. Provide Context
Include relevant context information when creating errors:

```python
# Good
raise DebuggerError(
    "Failed to set breakpoint",
    operation="set_breakpoint",
    thread_id=thread_id,
    details={"file": file, "line": line}
)

# Avoid  
raise DebuggerError("Breakpoint failed")
```

### 3. Use Decorators for Consistency
Prefer decorator-based error handling for methods:

```python
# Good
@async_handle_adapter_errors("launch")
async def _handle_launch(self, request):
    # Method implementation
    pass

# Avoid
async def _handle_launch(self, request):
    try:
        # Method implementation
        pass
    except Exception as e:
        # Manual error handling
        pass
```

### 4. Chain Exceptions
Always chain exceptions to preserve the original cause:

```python
# Good
raise IPCError("Connection failed") from original_exception

# Avoid
raise IPCError("Connection failed")
```

## Migration Guide

When updating existing code to use standardized error handling:

1. **Identify bare `except Exception:` clauses** - Replace with appropriate decorators
2. **Add specific error types** - Replace generic exceptions with specific DapperError types
3. **Add context information** - Include operation names, IDs, and other relevant details
4. **Use centralized response creation** - Replace manual error response creation with `create_dap_response`

### Example Migration

**Before:**
```python
async def _handle_attach(self, request):
    try:
        config = DapperConfig.from_attach_request(request)
        config.validate()
        await self.server.debugger.attach(**config.to_attach_kwargs())
    except ConfigurationError as e:
        return create_dap_response(e, request["seq"], "attach")
    except Exception as e:
        if "connection" in str(e).lower():
            ipc_error = IPCError(f"Failed to connect: {e}", cause=e)
            return create_dap_response(ipc_error, request["seq"], "attach")
        return create_dap_response(e, request["seq"], "attach")
    
    return {"success": True, "command": "attach"}
```

**After:**
```python
@async_handle_adapter_errors("attach")
async def _handle_attach(self, request):
    """Handle attach request."""
    config = DapperConfig.from_attach_request(request)
    config.validate()
    
    await self.server.debugger.attach(**config.to_attach_kwargs())
    
    return {"success": True, "command": "attach"}
```

## Error Handling in Tests

When testing error scenarios, use the specific error types:

```python
import pytest
from dapper.errors import IPCError

async def test_attach_connection_error():
    with pytest.raises(IPCError) as exc_info:
        await adapter._handle_attach(invalid_request)
    
    assert "connection" in str(exc_info.value)
    assert exc_info.value.transport == "tcp"
```

## Logging

All error decorators automatically log errors with appropriate context. The logging includes:
- Error message and type
- Operation context
- Full traceback for debugging
- Structured details for analysis

No manual logging is needed when using the decorators - it's handled automatically.
