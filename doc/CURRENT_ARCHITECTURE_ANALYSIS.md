# Dapper Debugger Current Architecture Analysis

## Overview

This document analyzes Dapper's current debugging architecture to understand how tracing works and identify integration points for frame evaluation optimizations.

## Current Debugging Architecture

### Core Components

#### 1. DebuggerBDB (`dapper/debugger_bdb.py`)
- **Base Class**: Extends Python's built-in `bdb.Bdb` debugger
- **Primary Function**: Handles all breakpoint logic and tracing callbacks
- **Key Methods**:
  - `user_line(frame)`: Called on every line execution when tracing is active
  - `user_exception(frame, exc_info)`: Called when exceptions occur
  - `user_call(frame, argument_list)`: Called on function calls for function breakpoints
  - `set_break(path, line, cond)`: Sets line breakpoints
  - `run(cmd)`: Starts debugging with `sys.settrace()`

#### 2. PyDebugger (`dapper/server.py`)
- **Role**: Main debug adapter controller (asyncio-based)
- **Responsibilities**: 
  - Manages DAP protocol communication
  - Coordinates between client and debuggee
  - Handles subprocess vs in-process execution modes
  - Manages thread state and breakpoints storage

#### 3. InProcessDebugger (`dapper/core/inprocess_debugger.py`)
- **Purpose**: Lightweight wrapper for in-process debugging mode
- **Features**: Event-based communication instead of IPC/binary framing
- **Integration**: Wraps DebuggerBDB with explicit APIs

#### 4. Debug Launcher (`dapper/launcher/debug_launcher.py`)
- **Function**: Entry point for debuggee process
- **Communication**: Sends/receives commands via IPC (binary framing)
- **Modes**: Supports subprocess debugging with mandatory IPC

## Current Tracing Flow

### 1. Debuggee Startup
```
main() -> parse_args() -> configure_debugger() -> run_with_debugger() -> dbg.run()
```

### 2. Tracing Activation
```python
# In DebuggerBDB.run() (inherited from bdb.Bdb)
sys.settrace(self.trace_dispatch)
```

### 3. Line-by-Line Execution
```
sys.settrace() -> trace_dispatch() -> user_line() -> breakpoint checks -> stopped event
```

### 4. Breakpoint Handling
```python
def user_line(self, frame):
    filename = frame.f_code.co_filename
    line = frame.f_lineno
    
    # Check data watches
    changed_name = self._check_data_watch_changes(frame)
    
    # Check regular breakpoints  
    if self._handle_regular_breakpoint(filename, line, frame):
        return
    
    # Handle stepping/entry stops
    self._emit_stopped_event(frame, thread_id, reason)
```

## Current Breakpoint Management

### Storage Structure
```python
# In DebuggerBDB
self.breakpoints = {}  # filename -> {line: breakpoint_info}
self.function_breakpoints = []  # List of function names
self.breakpoint_meta = {}  # (path, line) -> metadata
```

### Setting Breakpoints
```python
# Flow: DAP request -> PyDebugger.set_breakpoints() -> DebuggerBDB.set_break()
def set_break(self, filename, lineno, temporary=False, cond=None):
    # Uses bdb.Bdb.set_break() which stores in self.breaks
    # Custom metadata stored in self.breakpoint_meta
```

### Breakpoint Checking
```python
def _handle_regular_breakpoint(self, filename, line, frame):
    # 1. Check if breakpoint exists at this line
    # 2. Evaluate condition if present
    # 3. Check hit condition
    # 4. Handle log messages
    # 5. Emit stopped event if breakpoint should hit
```

## Communication Architecture

### Subprocess Mode (Default)
```
Client <-> Debug Adapter (asyncio) <-> IPC (binary framing) <-> Debug Launcher (bdb)
```

### In-Process Mode (Opt-in)
```
Client <-> Debug Adapter (background thread) <-> InProcessDebugger (direct calls)
```

## Performance Characteristics

### Current Tracing Overhead
1. **Every Line**: `user_line()` called for ALL executed lines
2. **Frame Inspection**: Full frame analysis on each call
3. **Breakpoint Lookup**: Dictionary checks for every line
4. **Data Watch Checking**: Variable comparison on each step
5. **Thread Management**: Thread registration and tracking

### Bottlenecks Identified
1. **Universal Tracing**: No selective tracing - all frames traced
2. **Python-Level Callbacks**: Every trace event crosses Python/C boundary
3. **Repeated Computations**: Breakpoint validity checked repeatedly
4. **No Bytecode Optimization**: Breakpoints checked at runtime vs compile-time

## Integration Points for Frame Evaluation

### 1. DebuggerBDB.run() Method
**Current**: `sys.settrace(self.trace_dispatch)`
**Frame Eval**: Replace with frame evaluation hook setup

### 2. Breakpoint Setting
**Current**: Store in dictionaries, check at runtime
**Frame Eval**: Pre-compile breakpoints into bytecode

### 3. Thread Management
**Current**: Thread registration in `user_line()`
**Frame Eval**: Thread-local storage in C-level

### 4. Communication
**Current**: Events sent from Python callbacks
**Frame Eval**: Same event system, but triggered from C-level

## Architecture Compatibility Assessment

### ✅ Compatible Components
1. **DAP Protocol Layer**: No changes needed
2. **IPC Communication**: Works with both modes
3. **Breakpoint Storage**: Can be adapted for caching
4. **Event System**: Compatible with frame evaluation triggers

### ⚠️ Adaptation Required
1. **DebuggerBDB**: Need frame evaluation variant
2. **Tracing Callbacks**: Replace with selective tracing
3. **Performance Monitoring**: Add frame evaluation metrics
4. **Configuration**: Add frame evaluation options

### ❌ Potential Conflicts
1. **bdb.Bdb Inheritance**: Frame evaluation may not fit bdb model
2. **Stepping Logic**: May need redesign for selective tracing
3. **Exception Handling**: Integration complexity with frame eval

## Recommended Integration Strategy

### Phase 1: Hybrid Approach
- Keep existing DebuggerBDB for compatibility
- Add optional FrameEvalDebugger alongside
- Allow runtime switching between modes

### Phase 2: Gradual Migration
- Move common functionality to shared base
- Implement frame evaluation optimizations
- Maintain backward compatibility

### Phase 3: Full Integration
- Unified debugger supporting both modes
- Automatic mode selection based on configuration
- Performance-based fallbacks

## Key Files for Modification

### Primary Integration Points
1. `dapper/debugger_bdb.py` - Core tracing logic
2. `dapper/debug_launcher.py` - Debuggee startup
3. `dapper/inprocess_debugger.py` - In-process mode
4. `dapper/server.py` - Main debugger controller

### Supporting Files
1. `dapper/debug_shared.py` - Shared state management
2. `dapper/ipc_context.py` - IPC configuration
3. `dapper/protocol_types.py` - DAP protocol types

## Testing Considerations

### Existing Test Compatibility
- Most tests should work with frame evaluation disabled
- Need frame evaluation-specific test suite
- Performance regression tests required

### Test Strategy
1. **Unit Tests**: Individual component testing
2. **Integration Tests**: Full debugging scenarios
3. **Performance Tests**: Benchmarking vs current tracing
4. **Compatibility Tests**: Ensure backward compatibility

## Conclusion

Dapper's current architecture is well-structured for frame evaluation integration. The separation between debug adapter and debuggee, along with the existing in-process mode, provides a solid foundation for implementing high-performance frame evaluation optimizations while maintaining backward compatibility.
