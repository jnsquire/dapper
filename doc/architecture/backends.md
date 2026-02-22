# Backend Lifecycle Management Guide

This guide describes the standardized lifecycle management system implemented for Dapper debugger backends, providing consistent state tracking, resource cleanup, and error handling across all backend implementations.

## Overview

The lifecycle management system addresses several issues that existed in the original backend implementations:

- **Inconsistent initialization patterns** across different backends
- **No standardized state tracking** or availability checks
- **Inconsistent shutdown handling** and resource cleanup
- **Missing protocol compliance** for `launch()` and `attach()` methods
- **No error recovery mechanisms**

## Architecture

### Core Components

#### 1. BackendLifecycleState Enum
```python
class BackendLifecycleState(Enum):
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
```

#### 2. LifecycleManager Class
The `LifecycleManager` provides:
- **State transition validation** with enforced valid transitions
- **Operation context management** with automatic state tracking
- **Cleanup callback registration** for resource management
- **Error tracking and recovery** capabilities
- **Thread-safe operations** using asyncio locks

#### 3. BaseBackend Integration
All backends now inherit from `BaseBackend` which includes:
- **Standardized initialization** through `initialize()` method
- **Protocol compliance** with `launch()` and `attach()` methods
- **Automatic state management** for all operations
- **Consistent error handling** and logging

## State Transitions

### Valid State Flow
```
UNINITIALIZED → INITIALIZING → READY → BUSY ↔ READY
                     ↓           ↓           ↓
                   ERROR ←─────┘    TERMINATING → TERMINATED
```

### State Descriptions

| State | Description | Operations Allowed |
|-------|-------------|-------------------|
| UNINITIALIZED | Backend created but not initialized | `initialize()` |
| INITIALIZING | Backend is setting up resources | None (transition only) |
| READY | Backend ready for operations | All debug operations |
| BUSY | Backend is executing an operation | None (operation in progress) |
| ERROR | Backend encountered an error | `recover()` or `terminate()` |
| TERMINATING | Backend is shutting down | None (cleanup in progress) |
| TERMINATED | Backend fully shut down | None (final state) |

## Usage Examples

### Backend Initialization
```python
# InProcessBackend
backend = InProcessBackend(bridge)
await backend.initialize()  # Transitions: UNINITIALIZED → INITIALIZING → READY

# ExternalProcessBackend  
backend = ExternalProcessBackend(ipc, loop, ...)
await backend.initialize()  # Validates IPC connection and process state
```

### Launch and Attach
```python
# Launch new debuggee
await backend.launch(config)  # Calls initialize() internally

# Attach to existing debuggee
await backend.attach(config)  # Calls initialize() internally
```

### Operation Context
```python
# All operations automatically use lifecycle context
async def set_breakpoints(self, path, breakpoints):
    response = await self._execute_with_timeout(
        "set_breakpoints",
        {"path": path, "breakpoints": breakpoints}
    )
    # State automatically: READY → BUSY → READY (on success)
    # Or: READY → BUSY → ERROR (on failure)
```

### Error Handling and Recovery
```python
# Check backend state
if backend.lifecycle_state == BackendLifecycleState.ERROR:
    print(f"Backend error: {backend.error_info}")
    await backend.recover()  # Attempt recovery

# Graceful shutdown
await backend.terminate()  # READY → TERMINATING → TERMINATED
```

## Implementation Details

### Resource Cleanup
Backends register cleanup callbacks during initialization:

```python
# In constructor
self._lifecycle.add_cleanup_callback(self._cleanup_ipc)
self._lifecycle.add_cleanup_callback(self._cleanup_commands)

# Cleanup methods called automatically during termination
def _cleanup_ipc(self):
    if hasattr(self._ipc, 'close'):
        self._ipc.close()
```

### Operation Context Manager
All backend operations use the lifecycle context manager:

```python
async with self._lifecycle.operation_context("set_breakpoints"):
    # Backend state automatically set to BUSY
    # Operation executes here
    # State automatically restored to READY or set to ERROR
```

### Error Tracking
When errors occur, they're automatically tracked:

```python
try:
    await self._execute_command(command)
except Exception as e:
    await self._lifecycle.mark_error(f"Command failed: {e}")
    raise
```

## Migration Guide

### For Existing Backend Implementations

1. **Inherit from BaseBackend** instead of direct protocol implementation
2. **Implement `_execute_command()`** method instead of individual operation methods
3. **Add lifecycle-aware initialization** in `initialize()` method
4. **Register cleanup callbacks** in constructor
5. **Remove manual state tracking** - handled by LifecycleManager

### Before
```python
class MyBackend:
    def __init__(self):
        self._available = True
    
    def is_available(self):
        return self._available
    
    async def set_breakpoints(self, path, breakpoints):
        try:
            # Manual implementation
            pass
        except Exception:
            self._available = False
```

### After
```python
class MyBackend(BaseBackend):
    def __init__(self):
        super().__init__()
        self._lifecycle.add_cleanup_callback(self._cleanup)
    
    async def _execute_command(self, command, args, **kwargs):
        # Centralized command handling
        if command == "set_breakpoints":
            return await self._handle_set_breakpoints(args)
        # ... other commands
    
    async def initialize(self):
        await self._lifecycle.initialize()
        # Setup logic here
        await self._lifecycle.mark_ready()
```

## Benefits Achieved

### 1. Consistency
- **Standardized state tracking** across all backends
- **Uniform error handling** and recovery patterns
- **Consistent resource management** and cleanup

### 2. Reliability
- **Automatic state validation** prevents invalid operations
- **Guaranteed cleanup** through callback system
- **Error recovery** capabilities

### 3. Maintainability
- **Reduced boilerplate** code in backend implementations
- **Centralized lifecycle logic** easier to maintain
- **Better debugging** with detailed state information

### 4. Protocol Compliance
- **All backends implement** `launch()` and `attach()` methods
- **Consistent interface** for debugger operations
- **Better integration** with Dapper configuration system

## Testing Considerations

### Unit Testing
```python
async def test_backend_lifecycle():
    backend = InProcessBackend(mock_bridge)
    
    # Test initialization
    assert backend.lifecycle_state == BackendLifecycleState.UNINITIALIZED
    await backend.initialize()
    assert backend.lifecycle_state == BackendLifecycleState.READY
    
    # Test error handling
    with pytest.raises(RuntimeError):
        await backend._execute_command("invalid_command")
    assert backend.lifecycle_state == BackendLifecycleState.ERROR
    
    # Test recovery
    await backend.recover()
    assert backend.lifecycle_state == BackendLifecycleState.READY
```

### Integration Testing
- Test backend lifecycle in full debugging scenarios
- Verify cleanup callbacks are executed
- Test error recovery under various failure conditions

## Future Enhancements

### Planned Improvements
1. **Metrics collection** for lifecycle events
2. **Health check endpoints** for monitoring
3. **Graceful degradation** strategies
4. **Backend hot-swapping** capabilities

### Extension Points
- **Custom state transitions** for specialized backends
- **Plugin cleanup callbacks** for resource management
- **Event hooks** for lifecycle state changes

## Troubleshooting

### Common Issues

1. **Backend stuck in ERROR state**
   - Check `backend.error_info` for details
   - Call `await backend.recover()` to attempt recovery
   - Verify all resources are properly cleaned up

2. **Initialization failures**
   - Ensure all dependencies are available
   - Check IPC connections and process states
   - Verify configuration parameters

3. **Resource leaks**
   - Ensure all cleanup callbacks are registered
   - Test termination process thoroughly
   - Monitor resource usage during operations

### Debug Information
```python
# Get current state and error info
print(f"State: {backend.lifecycle_state}")
print(f"Available: {backend.is_available()}")
print(f"Ready: {backend.is_ready()}")
print(f"Error info: {backend.error_info}")
```

This lifecycle management system provides a solid foundation for reliable, maintainable debugger backends with consistent behavior across all implementations.
