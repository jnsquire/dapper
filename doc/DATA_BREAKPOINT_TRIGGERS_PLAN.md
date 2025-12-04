# Data Breakpoint Runtime Triggers - Implementation Plan

This document outlines the plan to implement runtime watchpoint triggers for data breakpoints, completing the Phase 3 feature mentioned in `CHECKLIST.md`.

## Current State

### What's Implemented 



1. **DAP Protocol Support** (`adapter/server.py`, `adapter/request_handlers.py`)
   - `dataBreakpointInfo` request handler returns a `dataId` pattern: `frame:{id}:var:{name}`
   - `setDataBreakpoints` request handler stores watch metadata in `_data_watches` and `_frame_watches`
   - Server advertises `supportsDataBreakpoints` capability

2. **Core Data Breakpoint State** (`core/data_breakpoint_state.py`)
   - `DataBreakpointState` dataclass consolidates all watchpoint state:
     - `watch_names`: set of variable names being watched
     - `watch_meta`: metadata dict (conditions, hit counts)
     - `last_values_by_frame` / `global_values`: value snapshots for change detection
   - `register_watches()`, `check_for_changes()`, `update_snapshots()` methods

3. **In-Process Debugger Integration** (`core/debugger_bdb.py`)
   - `register_data_watches()` method registers watches with `DataBreakpointState`
   - `user_line()` already checks for data watch changes and emits `stopped` events with reason `"data breakpoint"`
   - `_should_stop_for_data_breakpoint()` evaluates conditions/hit conditions

4. **Adapter ↔ In-Process Bridge** (`adapter/inprocess_bridge.py`, `adapter/server.py`)
   - `set_data_breakpoints()` bridges watches to in-process debugger via `register_data_watches()`

5. **Tests** (`tests/unit/test_data_breakpoint_triggers.py`)
   - Unit tests verify that in-process mode triggers on variable changes

### What's Missing ❌

**Runtime triggers in subprocess mode** — the debug launcher runs in a separate process and does not currently:
1. Receive `setDataBreakpoints` commands via IPC
2. Register watches with the subprocess's `DebuggerBDB` instance
3. Report data breakpoint stops back through IPC

---

## Implementation Plan

### Phase 1: Launcher Command Handler for setDataBreakpoints

**Goal:** Enable the subprocess debugger to receive and register data breakpoint configurations.

**Files to modify:**
- `dapper/shared/command_handlers.py`

**Tasks:**
1. Update `_handle_set_data_breakpoints_impl()` to extract variable names from `dataId` patterns
2. Call `dbg.register_data_watches(names, metas)` to register with the BDB instance
3. Return verified status for each breakpoint

```python
# Pseudocode for enhanced handler
def _handle_set_data_breakpoints_impl(dbg, arguments):
    breakpoints = arguments.get("breakpoints", [])
    
    watch_names = []
    watch_metas = []
    
    for bp in breakpoints:
        data_id = bp.get("dataId", "")
        # Parse "frame:123:var:x" pattern
        if ":var:" in data_id:
            var_name = data_id.split(":var:")[-1]
            watch_names.append(var_name)
            meta = {
                "dataId": data_id,
                "accessType": bp.get("accessType", "write"),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
            }
            watch_metas.append((var_name, meta))
    
    # Register with debugger
    register = getattr(dbg, "register_data_watches", None)
    if callable(register):
        register(watch_names, watch_metas)
    
    return {"breakpoints": [{"verified": True} for _ in breakpoints]}
```

---

### Phase 2: Ensure user_line Triggers in Subprocess Mode

**Goal:** Confirm that `DebuggerBDB.user_line()` properly emits `stopped` events for data breakpoints in subprocess mode.

**Files to verify/modify:**
- `dapper/core/debugger_bdb.py` (likely no changes needed)
- `dapper/launcher/comm.py` (verify `send_debug_message` works for stopped events)

**Current behavior in `user_line()`:**
```python
# Already implemented:
changed_name = self._check_data_watch_changes(frame)
self._update_watch_snapshots(frame)

if changed_name and self._should_stop_for_data_breakpoint(changed_name, frame):
    self._emit_stopped_event(frame, thread_id, "data breakpoint", f"{changed_name} changed")
    return
```

**Tasks:**
1. Verify `_emit_stopped_event` calls `send_message("stopped", ...)` which is wired to `send_debug_message` in subprocess mode
2. Add integration test for subprocess mode data breakpoint triggers

---

### Phase 3: Adapter-Side Event Handling

**Goal:** Ensure the adapter properly relays `stopped` events with reason `"data breakpoint"` to the DAP client.

**Files to verify:**
- `dapper/adapter/server.py` - IPC event handling
- `dapper/ipc/ipc_receiver.py` - event routing

**Tasks:**
1. Verify stopped events from subprocess are relayed to DAP client unchanged
2. Add test to confirm end-to-end flow

---

### Phase 4: Enhanced dataBreakpointInfo Response

**Goal:** Provide richer information in `dataBreakpointInfo` response for better VS Code UI support.

**Files to modify:**
- `dapper/adapter/server.py` - `data_breakpoint_info()` method
- `dapper/shared/command_handlers.py` - `_handle_data_breakpoint_info_impl()`

**Enhancements:**
1. Include variable type information if available
2. Support memory address-based dataIds for more precise tracking
3. Indicate whether the variable supports read vs write access types

```python
def data_breakpoint_info(self, *, name: str, frame_id: int, variables_reference: int = 0) -> DataBreakpointInfoResponseBody:
    # Look up variable in the referenced scope
    var_info = self._lookup_variable(variables_reference, name, frame_id)
    
    if var_info is None:
        return {"dataId": None, "description": f"Variable '{name}' not found"}
    
    data_id = f"frame:{frame_id}:var:{name}"
    return {
        "dataId": data_id,
        "description": f"Break when '{name}' changes",
        "accessTypes": ["write"],  # Python primarily supports write detection
        "canPersist": False,
    }
```

---

### Phase 5: Read Access Detection (Optional/Future)

**Goal:** Support breaking on variable reads, not just writes.

**Complexity:** High — requires deeper integration with Python's tracing or using `__getattribute__` hooks.

**Approach options:**
1. **Object proxying:** Wrap watched objects in a proxy that intercepts `__getattribute__`
2. **Trace function enhancement:** Not directly supported by sys.settrace for reads
3. **AST rewriting:** Transform source to inject read detection (complex)

**Recommendation:** Defer this to a future phase and document that only "write" access type is currently supported.

---

## Test Plan

### Unit Tests

1. **test_launcher_setDataBreakpoints_command.py**
   - Verify `_handle_set_data_breakpoints_impl()` correctly parses dataIds
   - Verify `register_data_watches()` is called with correct names and metas

2. **test_data_breakpoint_triggers.py** (existing, extend)
   - Add test for condition evaluation
   - Add test for hit condition counting

### Integration Tests

1. **test_data_breakpoint_subprocess.py** (new)
   - Launch subprocess with data breakpoint configuration
   - Execute code that modifies watched variable
   - Verify stopped event is received with reason "data breakpoint"

2. **test_data_breakpoint_end_to_end.py** (new)
   - Full DAP client → adapter → launcher → stopped event flow
   - Verify VS Code would see the expected stopped event

---

## Implementation Order

| Step | Task | Effort | Dependency |
|------|------|--------|------------|
| 1 | Update `_handle_set_data_breakpoints_impl()` | Small | None |
| 2 | Add unit tests for launcher handler | Small | Step 1 |
| 3 | Verify subprocess stopped event relay | Small | Step 1 |
| 4 | Add integration test for subprocess mode | Medium | Steps 1-3 |
| 5 | Enhance `dataBreakpointInfo` response | Small | None |
| 6 | Update CHECKLIST.md | Trivial | Steps 1-4 |
| 7 | Document data breakpoint feature | Small | Steps 1-5 |

**Estimated Total Effort:** 1-2 days

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance impact from value comparisons | Medium | Only compare watched variables, use identity check first |
| Complex objects hard to compare | Low | Use `==` with fallback to identity; document limitations |
| Thread safety for multi-threaded programs | Medium | Lock around snapshot updates; document thread limitations |
| IPC reliability for stopped events | Low | Already battle-tested for other stopped reasons |

---

## Success Criteria

1. ✅ User can set a data breakpoint on a variable in VS Code
2. ✅ Debugger stops when the variable's value changes (subprocess mode)
3. ✅ Debugger stops when the variable's value changes (in-process mode) — **already works**
4. ✅ Stopped event shows reason "data breakpoint" with variable name
5. ✅ Conditions and hit conditions work on data breakpoints
6. ✅ All existing tests continue to pass

---

## References

- DAP Specification: [Data Breakpoints](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_DataBreakpointInfo)
- Current implementation: `dapper/core/data_breakpoint_state.py`
- Related: `doc/CHECKLIST.md` Phase 3 items
