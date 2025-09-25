# Dapper AI Debugger Features Checklist

This document outlines the Debug Adapter Protocol (DAP) features implemented in Dapper, organized by category.

## Legend
- ✅ **Implemented**: Feature is fully implemented and tested
- 🟡 **Partial**: Feature is partially implemented or has basic support
- ❌ **Not Implemented**: Feature is not yet implemented
- 🔄 **In Progress**: Feature is currently being worked on

---

## Core Debugging Features

### Program Control
- ✅ **Launch**: Start a new Python program for debugging
  - Supports command line arguments
  - Supports stop-on-entry
  - Supports no-debug mode
- ✅ **Attach**: Attach to an already running Python process
- ✅ **Restart**: Restart the debugged program
- ✅ **Disconnect**: Disconnect from the debugged program
- ✅ **Terminate**: Force terminate the debugged program

### Execution Control
- ✅ **Continue**: Continue execution until next breakpoint
- ✅ **Pause**: Pause execution at current location
- ✅ **Next**: Step over to next line
- ✅ **Step In**: Step into function calls
- ✅ **Step Out**: Step out of current function
- ❌ **Reverse Continue**: Continue backwards in execution
- ❌ **Step Granularity**: Control stepping granularity (statement/line/instruction)

Note: `Pause` is supported in the debugger/launcher command path, however the adapter's `RequestHandler` currently has no `_handle_pause` method to accept a client-initiated `pause` request. Consider adding `_handle_pause` in `dapper/server.py` to expose this to clients.

---

## Breakpoints

### Source Breakpoints
- ✅ **Set Breakpoints**: Set/remove breakpoints in source files
  - Basic line breakpoints
  - Verified/unverified status
- 🟡 **Breakpoint Conditions**: Basic condition support
- ❌ **Hit Conditions**: Break after N hits
- ❌ **Log Points**: Log messages without stopping

### Function Breakpoints
### Function Breakpoints
- 🟡 **Set Function Breakpoints**: Set breakpoints on function names
  - Note: low-level support exists in the debugger and launcher (PyDebugger + debug launcher handlers), but the adapter `RequestHandler` currently does not expose a `_handle_setFunctionBreakpoints` method to DAP clients.
- ❌ **Function Breakpoint Conditions**: Conditions for function breakpoints

### Exception Breakpoints
### Exception Breakpoints
- 🟡 **Set Exception Breakpoints**: Break on raised/uncaught exceptions
  - Supports "uncaught" and "raised" filters
  - Note: the debugger and launcher support exception breakpoints, but the adapter currently lacks a `_handle_setExceptionBreakpoints` method on `RequestHandler` to expose this to clients.
- ❌ **Exception Options**: Advanced exception filtering options

### Data Breakpoints
- 🟡 **Data Breakpoints (Phase 1)**: Requests implemented (dataBreakpointInfo, setDataBreakpoints) and server advertises capability. Currently bookkeeping only – no runtime stop on change yet.
- ❌ **Watchpoints (runtime triggers)**: Break when variable values change (Phase 2 planned: compare stored values per line and emit `stopped` with reason `data breakpoint`).

---

## Runtime Information

### Threads
- ✅ **Threads**: Get list of active threads
  - Thread IDs and names
- ❌ **Thread Names**: Dynamic thread naming

### Stack Frames
- ✅ **Stack Trace**: Get stack frames for a thread
  - Frame IDs, names, source locations
  - Line and column information
- ❌ **Source References**: Handle source code not in filesystem

### Variables and Scopes
- ✅ **Scopes**: Get variable scopes for a frame
  - Local and Global scopes
- ✅ **Variables**: Get variables in a scope
  - Basic variable listing
- ✅ **Set Variable**: Modify variable values during debugging
  - Supports local and global scopes
  - Enhanced support for complex objects, lists, and dictionaries
  - Type conversion with context awareness
  - Expression evaluation for variable values
  - Object attribute modification
  - List element modification by index
  - Dictionary key-value setting
  - Error handling for invalid operations and immutable types
- 🟡 **Variable Presentation**: Rich variable display hints
  - Supported fields (DAP VariablePresentationHint):
    - `kind` (string): semantic kind; recommended values include `property`, `method`, `class`, `data`, `event`, `baseClass`, `innerClass`, `interface`, `mostDerivedClass`, `virtual`.
    - `attributes` (string[]): badges/flags; recommended values include `static`, `constant`, `readOnly`, `rawString`, `hasObjectId`, `canHaveObjectId`, `hasSideEffects`, `hasDataBreakpoint`.
    - `visibility` (string): `public`, `private`, `protected`, `internal`, `final`.
    - `lazy` (boolean): when true, the client should present a UI affordance to fetch the value (useful for getters or expensive evaluations). When `lazy` is used, `variablesReference` is expected to point at the value provider.
  - Notes: The adapter returns these hints as part of each `Variable`'s `presentationHint`. Clients may map `kind` and `attributes` to icons, styles, or tooltips. Prefer `hasDataBreakpoint` attribute over the deprecated `dataBreakpoint` kind.
  - Examples:
    - Property (read-only):

      ```json
      {
        "presentationHint": { "kind": "property", "attributes": ["readOnly"], "visibility": "public" }
      }
      ```

    - Lazy property (expensive getter):

      ```json
      {
        "presentationHint": { "kind": "property", "lazy": true, "attributes": ["canHaveObjectId"] },
        "variablesReference": 123
      }
      ```

### Expression Evaluation
- 🟡 **Evaluate**: Evaluate expressions in debug context
  - Basic expression evaluation
  - Supports different contexts (hover, watch, etc.)
- ❌ **Set Expression**: Set expressions for watchpoints
- ❌ **Completions**: Auto-complete for expressions

---

## Advanced Features

### Source Code
- ✅ **Loaded Sources**: List all loaded source files
- ❌ **Source**: Request source code content
- ❌ **Goto Targets**: Find possible goto locations

### Modules
- ✅ **Modules**: List loaded modules
- ❌ **Module Source**: Get module source code

### Exceptions
- ✅ **Exception Info**: Detailed exception information
- ❌ **Set Exception Breakpoints**: Advanced exception filtering

### Configuration
- ✅ **Initialize**: Basic DAP initialization
- ✅ **Configuration Done**: Signal configuration completion
- ✅ **Capabilities**: Report supported features

---

## Implementation Status Summary

### Current Implementation Level: **Basic Debugging Support**

**Implemented (20/35 features - 57%)**
- Core program control (launch, disconnect, terminate)
- Basic execution control (continue, pause, stepping)
- Breakpoint management (source, function, exception)
- Runtime inspection (threads, stack, variables, scopes)
- Variable modification (set variable)
- Basic expression evaluation
- Configuration management (initialize, configurationDone)

**Partially Implemented (1/35 features - 3%)**
- Expression evaluation (basic support, needs enhancement)

**Not Implemented (14/35 features - 40%)**
- Advanced execution control (reverse debugging, step granularity)
- Advanced breakpoints (hit conditions, log points, data breakpoints)
- Advanced runtime features (completions)
- Source code management
- Exception details
- Configuration management

---

## Priority Implementation Order

### High Priority (Essential for basic debugging)
1. ~~**Attach**~~ - ✅ Attach to running processes
2. ~~**Terminate**~~ - ✅ Force terminate debugged programs  
3. ~~**Restart**~~ - ✅ Restart debugged programs
4. ~~**Set Variable**~~ - ✅ Modify variables during debugging
5. ~~**Exception Info**~~ - ✅ Detailed exception information

### Medium Priority (Enhanced debugging experience)
1. ~~**Configuration Done**~~ - ✅ Proper configuration management
2. ~~**Loaded Sources**~~ - ✅ Source file management
3. ~~**Modules**~~ - ✅ Module inspection
4. **Completions** - Expression auto-completion
5. **Source References** - Handle dynamic source code

### Low Priority (Advanced features)
1. **Reverse Debugging** - Step back, reverse continue
2. **Data Breakpoints** - Variable watchpoints
3. **Log Points** - Non-stopping breakpoints
4. **Goto Targets** - Navigation features
5. **Step Granularity** - Fine-grained stepping control

---

## Testing Coverage

Current test coverage for debugger features:
- **debugger.py**: 64% coverage
- **server.py**: 82% coverage (DAP request handling)
- **Total**: 56% overall coverage

### Well Tested Features
- ✅ Launch process
- ✅ Set breakpoints
- ✅ Execution control (continue, pause, stepping)
- ✅ Thread management
- ✅ Stack trace retrieval
- ✅ Variable inspection
- ✅ Variable modification

### Under Tested Features
- 🟡 Exception breakpoints
- 🟡 Function breakpoints
- 🟡 Expression evaluation
- ❌ Advanced DAP features (not implemented yet)

---

## Future Development Roadmap

### Phase 1: Complete Basic Features (Current Priority)
- Implement attach, restart
- Enhance expression evaluation
- ~~Add set variable functionality~~ - ✅ Completed
- ~~Improve exception handling~~ - ✅ Exception Info implemented

### Phase 2: Enhanced Debugging Experience
- Add source code management
- Add auto-completion
- Improve variable presentation

### Phase 3: Advanced Features
- Reverse debugging capabilities
- Data breakpoints and watchpoints
- Log points and hit conditions
- Performance profiling integration

---

*Last updated: September 16, 2025*
*Coverage data: 56% overall, 64% debugger module*
