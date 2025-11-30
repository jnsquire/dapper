# IPC Transport Refactoring Guide

This document describes the refactoring of the IPC transport logic for better maintainability, separation of concerns, and extensibility.

## Overview

The original IPC implementation had several maintainability issues:
- Large monolithic `IPCContext` class (492 lines) with mixed responsibilities
- Complex connection logic scattered across methods
- Platform-specific code mixed throughout
- No clear abstraction between transport types
- Difficult to test and extend

## New Architecture

The refactored architecture follows the Factory pattern with clear separation of concerns:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   IPCManager    │───▶│  TransportFactory │───▶│ ConnectionBase  │
│                 │    │                  │    │                 │
│ - High-level    │    │ - Creates         │    │ - Base class    │
│   IPC ops       │    │   transport-      │    │ - Common        │
│ - Thread mgmt   │    │   specific        │    │   interface     │
│ - Cleanup       │    │   connections     │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │   TransportConfig    │
                    │                      │
                    │ - Transport settings │
                    │ - Platform params    │
                    │ - Binary mode        │
                    └──────────────────────┘
```

## Key Components

### 1. TransportFactory
**Purpose**: Creates transport-specific connections using the Factory pattern.

**Responsibilities**:
- Transport type resolution ("auto", "pipe", "unix", "tcp")
- Platform-specific transport selection
- Connection creation and configuration
- Error handling and fallback logic

**Key Methods**:
```python
@staticmethod
def create_listener(config: TransportConfig) -> tuple[ConnectionBase, list[str]]
    # Creates a listener and returns launcher arguments

@staticmethod  
def create_connection(config: TransportConfig) -> ConnectionBase
    # Creates a client connection to existing endpoint
```

### 2. IPCManager
**Purpose**: High-level IPC management with clean interface.

**Responsibilities**:
- Connection lifecycle management
- Reader thread management
- Message handling coordination
- Resource cleanup

**Key Methods**:
```python
def create_listener(config: TransportConfig) -> list[str]
    # Creates listener using factory

def connect(config: TransportConfig) -> None  
    # Connects to existing endpoint

def start_reader(message_handler: Callable, accept: bool) -> None
    # Starts message reader thread

def send_message(message: dict[str, Any]) -> None
    # Sends message through connection
```

### 3. TransportConfig
**Purpose**: Configuration dataclass for transport settings.

**Fields**:
```python
@dataclass
class TransportConfig:
    transport: str = "auto"
    host: str = "127.0.0.1" 
    port: int | None = None
    path: str | None = None
    pipe_name: str | None = None
    use_binary: bool = True
```

### 4. ConnectionBase
**Purpose**: Abstract base class for all connection types.

**Interface**:
```python
class ConnectionBase(ABC):
    async def accept() -> None
    async def close() -> None
    async def read_message() -> dict[str, Any] | None
    async def write_message(message: dict[str, Any]) -> None
```

### 5. IPCContextAdapter
**Purpose**: Backward compatibility layer.

**Benefits**:
- Existing code continues to work unchanged
- Gradual migration path
- Maintains all legacy attribute access
- Delegates to new architecture internally

## Migration Strategy

### Phase 1: Foundation (Complete)
- ✅ Created new architecture components
- ✅ Implemented backward compatibility adapter
- ✅ Updated server.py to use new components
- ✅ Maintained existing functionality

### Phase 2: Gradual Migration (Next)
- Migrate individual components to use new interfaces
- Update tests to work with new architecture
- Remove legacy adapter dependencies

### Phase 3: Cleanup (Future)
- Remove IPCContextAdapter once migration complete
- Clean up any remaining legacy code
- Update documentation

## Benefits Achieved

### 1. **Separation of Concerns**
- Transport creation logic isolated in Factory
- Connection management isolated in Manager
- Platform-specific code properly separated

### 2. **Improved Testability**
- Each component can be tested independently
- Mock objects easier to create
- Platform-specific logic can be tested separately

### 3. **Better Extensibility**
- New transport types easy to add
- Connection behavior easy to customize
- Configuration handling centralized

### 4. **Cleaner Code**
- Smaller, focused classes
- Clear responsibilities
- Reduced complexity in individual methods

### 5. **Backward Compatibility**
- Existing code continues to work
- No breaking changes during migration
- Gradual adoption possible

## Usage Examples

### Using New Architecture Directly

```python
from dapper.ipc import IPCManager, TransportConfig

# Create manager
manager = IPCManager()

# Configure transport
config = TransportConfig(
    transport="auto",
    use_binary=True
)

# Create listener for launch
args = manager.create_listener(config)

# Start message handling
manager.start_reader(handle_message, accept=True)

# Send messages
manager.send_message({"type": "request", "command": "continue"})

# Cleanup
manager.cleanup()
```

### Using with DapperConfig Integration

```python
from dapper.config import DapperConfig
from dapper.ipc import IPCManager, TransportConfig

# Get configuration
config = DapperConfig.from_launch_request(request)

# Create transport config from DapperConfig
transport_config = TransportConfig(
    transport=config.ipc.transport,
    pipe_name=config.ipc.pipe_name,
    host=config.ipc.host,
    port=config.ipc.port,
    path=config.ipc.path,
    use_binary=config.ipc.use_binary
)

# Use with IPC manager
manager = IPCManager()
args = manager.create_listener(transport_config)
```

### Legacy Compatibility (Current)

```python
# Existing code continues to work unchanged
self.ipc.create_listener(transport="pipe", pipe_name="mypipe")
self.ipc.connect(transport="tcp", host="localhost", port=4711)
```

## Testing Strategy

### Unit Tests
- Test TransportFactory with different configurations
- Test IPCManager lifecycle methods
- Test individual connection types
- Test error handling and fallbacks

### Integration Tests  
- Test end-to-end connection scenarios
- Test message passing between components
- Test cleanup and resource management
- Test platform-specific behavior

### Compatibility Tests
- Verify legacy adapter works correctly
- Test migration scenarios
- Verify no breaking changes

## Performance Considerations

### Lazy Initialization
- Connections created only when needed
- Reader thread started only during active sessions
- Resources cleaned up promptly

### Memory Management
- Clear ownership of resources
- Proper cleanup in all scenarios
- No resource leaks

### Threading
- Single reader thread per IPC session
- Thread-safe state management
- Proper thread lifecycle

## Future Enhancements

### 1. **Async/Await Support**
- Full async interface for IPC operations
- Async context manager support
- Better integration with asyncio

### 2. **Additional Transports**
- WebSocket transport for web-based debugging
- Shared memory transport for same-machine performance
- Custom transport plugins

### 3. **Advanced Features**
- Connection pooling
- Automatic reconnection
- Performance monitoring
- Connection health checks

### 4. **Security**
- Transport encryption
- Authentication mechanisms
- Secure channel establishment

## Conclusion

The IPC refactoring provides a solid foundation for future development while maintaining backward compatibility. The new architecture is more maintainable, testable, and extensible than the original implementation.

The migration strategy allows for gradual adoption without disrupting existing functionality, making it a low-risk improvement with significant long-term benefits.
