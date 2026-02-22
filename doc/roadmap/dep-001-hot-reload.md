# DEP-001: Custom DAP Protocol Extensions for Hot Code Reloading

| Field         | Value                                    |
|---------------|------------------------------------------|
| **DEP**       | 001                                      |
| **Title**     | Custom DAP Protocol Extensions for Hot Code Reloading |
| **Author**    | Joel Squire                              |
| **Status**    | Draft                                    |
| **Created**   | 2026-02-21                               |
| **Requires**  | Python ≥ 3.9, DAP 1.65+                 |

---

## Abstract

This proposal defines the custom Debug Adapter Protocol (DAP) messages
required to support **Reload-and-Continue** in Dapper: a feature that lets
a user edit source while stopped at a breakpoint and apply the change
without restarting the debug session.

Three protocol extensions are introduced:

1. A **capability flag** (`supportsHotReload`) advertised in the
   `initialize` response.
2. A **custom request** (`dapper/hotReload`) sent by the client to
   trigger a module reload.
3. A **custom event** (`dapper/hotReloadResult`) emitted by the adapter
   after a reload completes, carrying diagnostic details the standard
   `loadedSource` event cannot express.

The existing standard DAP `loadedSource` event (already supported by
Dapper) is reused, with `reason: "changed"`, so that conforming editors
refresh gutter decorations and breakpoint markers without modification.

---

## Motivation

Python's `importlib.reload()` can apply source changes at runtime, but a
debugger must coordinate several subsystems — breakpoints, bytecode
caches, frame-eval tracing, variable references — for the reload to be
safe and observable.  A well-defined protocol surface lets:

- **DAP clients** (VS Code, other editors) trigger reloads with a single
  command and present structured feedback.
- **The adapter** validate preconditions (debugger is stopped, module is
  pure-Python) and return rich diagnostics rather than a generic error
  string.
- **Tests** exercise the feature against typed message contracts.

No standard DAP request covers "reload a module in the debuggee without
restarting the session".  The `restart` request terminates the entire
session.  A custom namespaced request is therefore required.

---

## Specification

### 1. Capability: `supportsHotReload`

Added to the `Capabilities` TypedDict returned in the `initialize`
response.

```python
# protocol/capabilities.py  (addition)
class Capabilities(TypedDict):
    ...
    supportsHotReload: NotRequired[bool]
```

**Semantics:** When `True`, the adapter accepts the `dapper/hotReload`
request.  Clients **must not** send the request unless this flag is set.

**Advertised in:** `RequestHandler._handle_initialize` response body.

---

### 2. Request: `dapper/hotReload`

#### 2.1 Command Name

```
"dapper/hotReload"
```

The `dapper/` prefix follows the DAP convention for adapter-specific
extensions (see DAP spec §"Custom messages").  The `RequestHandler`
dispatch converts `/` to `_`, so the handler method is
`_handle_dapper_hot_reload`.

#### 2.2 Arguments

```python
class HotReloadArguments(TypedDict):
    """Arguments for the 'dapper/hotReload' request."""

    source: Source
    # The source file to reload.  'path' is required; 'sourceReference'
    # is ignored (reload always operates on the file system).

    options: NotRequired[HotReloadOptions]
    # Optional behaviour overrides.
```

```python
class HotReloadOptions(TypedDict, total=False):
    """Per-request behaviour overrides for hot reload."""

    rebindFrameLocals: bool
    # Default: True.
    # When True the adapter walks every stopped frame and replaces
    # references to old function objects with the reloaded versions.
    # Set to False to apply the reload for future calls only.

    updateFrameCode: bool
    # Default: True (on CPython ≥ 3.12); ignored on older runtimes.
    # When True *and* rebindFrameLocals is True, the adapter attempts
    # to assign frame.f_code on frames currently executing functions
    # from the reloaded module, subject to structural compatibility.

    patchClassInstances: bool
    # Default: False.
    # When True the adapter also patches __class__ on live instances
    # whose class was defined in the reloaded module.  Experimental;
    # may cause TypeError on __slots__ classes.

    invalidatePycache: bool
    # Default: True.
    # Delete the corresponding __pycache__/*.pyc file before calling
    # importlib.reload() to guarantee fresh bytecode.
```

**Design notes:**

- `source` uses the existing `Source` TypedDict from
  `protocol/structures.py`.  Only `path` is semantically required; the
  adapter resolves the module via `sys.modules` file-path matching.
- All options default to safe, useful behaviour.  The options block is
  entirely optional — omitting it is equivalent to accepting all
  defaults.
- `HotReloadOptions` uses `total=False` so every field is optional
  individually, matching the pattern used by
  `DataBreakpointInfoArguments`.

#### 2.3 Request TypedDict

```python
class HotReloadRequest(TypedDict):
    """Request to reload a Python module during a debug session."""

    seq: int
    type: Literal["request"]
    command: Literal["dapper/hotReload"]
    arguments: HotReloadArguments
```

#### 2.4 Response Body

```python
class HotReloadResponseBody(TypedDict, total=False):
    """Body of the 'dapper/hotReload' response."""

    reloadedModule: str
    # Fully-qualified name of the module that was reloaded
    # (e.g. "mypackage.utils").

    reloadedPath: str
    # Absolute path of the reloaded file (after resolution).

    reboundFrames: int
    # Number of live stack frames whose locals were rebound.
    # 0 if rebindFrameLocals was False or no matching frames existed.

    updatedFrameCodes: int
    # Number of frames whose f_code was successfully reassigned.
    # 0 on CPython < 3.12 or if updateFrameCode was False.

    patchedInstances: int
    # Number of live instances whose __class__ was patched.
    # 0 if patchClassInstances was False.

    warnings: list[str]
    # Non-fatal diagnostic messages.  Examples:
    #   - "frame.f_code update skipped for foo(): co_varnames changed"
    #   - "closure function bar() skipped (captured cell variables)"
    #   - "3 stale .pyc files deleted"
    #   - "patchClassInstances skipped for Baz: uses __slots__"
```

#### 2.5 Response TypedDict

```python
class HotReloadResponse(TypedDict):
    """Response to the 'dapper/hotReload' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dapper/hotReload"]
    message: NotRequired[str]
    body: NotRequired[HotReloadResponseBody]
```

**Success / failure semantics:**

| Condition | `success` | `message` |
|-----------|-----------|-----------|
| Module reloaded, all steps completed | `True` | `None` |
| Module reloaded, some steps skipped | `True` | `None` (details in `body.warnings`) |
| Module not found in `sys.modules` | `False` | `"Module not loaded: <path>"` |
| File is a C extension (`.so`/`.pyd`) | `False` | `"Cannot reload C extension module"` |
| Debugger is not stopped | `False` | `"Hot reload requires the debugger to be stopped"` |
| `importlib.reload()` raises | `False` | `"Reload failed: <exception>"` |
| File does not exist | `False` | `"Source file not found: <path>"` |

---

### 3. Standard Event: `loadedSource` (reused)

After a successful reload the adapter emits the standard DAP
`loadedSource` event so that conforming clients refresh their source
views:

```json
{
  "seq": <n>,
  "type": "event",
  "event": "loadedSource",
  "body": {
    "reason": "changed",
    "source": {
      "name": "utils.py",
      "path": "/home/user/project/mypackage/utils.py"
    }
  }
}
```

Dapper already has infrastructure for this event:
- `payload_extractor._loaded_source()` formats the body.
- `PyDebugger.emit_event()` provides thread-safe event emission.

No new types are needed.

---

### 4. Custom Event: `dapper/hotReloadResult` (optional enrichment)

For clients that register interest (e.g. the Dapper VS Code extension),
a richer event is emitted **after** the `loadedSource` event:

```python
class HotReloadResultEventBody(TypedDict, total=False):
    """Body of the 'dapper/hotReloadResult' event."""

    module: str
    # Fully-qualified module name.

    path: str
    # Absolute file path.

    reboundFrames: int
    updatedFrameCodes: int
    patchedInstances: int

    warnings: list[str]
    # Same warnings as in the response body.  Duplicated here so that
    # clients that process events asynchronously (e.g. output channel
    # loggers) receive the diagnostics without correlating responses.

    durationMs: float
    # Wall-clock time for the reload operation in milliseconds.
```

```python
class HotReloadResultEvent(TypedDict):
    """Event emitted after a successful hot reload."""

    seq: int
    type: Literal["event"]
    event: Literal["dapper/hotReloadResult"]
    body: HotReloadResultEventBody
```

**Rationale:** The response body already carries the same data, but
events are routed through independent pipelines in many editors (debug
console, status bar, telemetry). Emitting a dedicated event simplifies
client-side wiring.

---

### 5. Payload Extractor Registration

A new extractor is added to `payload_extractor.py`:

```python
def _hot_reload_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "module": data.get("module", ""),
        "path": data.get("path", ""),
        "reboundFrames": data.get("reboundFrames", 0),
        "updatedFrameCodes": data.get("updatedFrameCodes", 0),
        "patchedInstances": data.get("patchedInstances", 0),
        "warnings": data.get("warnings", []),
        "durationMs": data.get("durationMs", 0.0),
    }

_EXTRACTORS["dapper/hotReloadResult"] = _hot_reload_result
```

---

## Message Sequence Diagram

```
Client (VS Code)                       Adapter (Dapper)
      │                                       │
      │  ── stopped event ──────────────────► │
      │     { reason: "breakpoint", ... }     │
      │                                       │
      │  (user edits source file on disk)     │
      │                                       │
      │  ── dapper/hotReload request ───────► │
      │     { source: { path: "…" },          │
      │       options: {} }                   │
      │                                       │
      │                          ┌────────────┤
      │                          │ 1. Resolve module from path
      │                          │ 2. Validate preconditions
      │                          │ 3. invalidate_caches()
      │                          │ 4. Delete .pyc
      │                          │ 5. linecache.checkcache()
      │                          │ 6. importlib.reload(mod)
      │                          │ 7. Invalidate frame-eval caches
      │                          │ 8. Clear + re-set breakpoints
      │                          │ 9. Rebind frame locals
      │                          │ 10. Emit events
      │                          └────────────┤
      │                                       │
      │  ◄── dapper/hotReload response ────── │
      │     { success: true,                  │
      │       body: {                         │
      │         reloadedModule: "pkg.utils",  │
      │         reboundFrames: 2,             │
      │         warnings: ["…"]               │
      │       } }                             │
      │                                       │
      │  ◄── loadedSource event ───────────── │
      │     { reason: "changed",              │
      │       source: { path: "…" } }         │
      │                                       │
      │  ◄── dapper/hotReloadResult event ──  │
      │     { module: "pkg.utils",            │
      │       durationMs: 42.3,               │
      │       warnings: ["…"] }               │
      │                                       │
      │  ── continue request ───────────────► │
      │     (execution resumes with new code) │
```

---

## Error Handling

### Pre-flight Validation (before `importlib.reload`)

| Check | Error response |
|-------|---------------|
| Debugger not in a stopped state | `success: false`, `message: "Hot reload requires the debugger to be stopped"` |
| `source.path` is empty or missing | `success: false`, `message: "Missing source path"` |
| File does not exist on disk | `success: false`, `message: "Source file not found: <path>"` |
| File is not a Python source (`.py`/`.pyw`) | `success: false`, `message: "Not a Python source file: <path>"` |
| No matching module in `sys.modules` | `success: false`, `message: "Module not loaded: <path>"` |
| Module is a C extension | `success: false`, `message: "Cannot reload C extension module"` |

### Post-reload Warnings (non-fatal, reported in `body.warnings`)

| Situation | Warning text |
|-----------|-------------|
| `frame.f_code` skipped: different `co_varnames` | `"frame.f_code update skipped for <func>(): co_varnames changed from <n> to <m>"` |
| `frame.f_code` skipped: CPython < 3.12 | `"frame.f_code update not available on Python <version>"` |
| Closure detected, rebinding skipped | `"Closure function <func>() skipped: captured cell variables cannot be safely rebound"` |
| `__slots__` class, patching skipped | `"Class <cls> uses __slots__; instance patching skipped"` |
| Module body raised during reload | `"Module body raised <exc> during re-execution (reload still applied)"` |
| `.pyc` deletion failed | `"Failed to delete stale .pyc: <path> (<error>)"` |

---

## Compatibility

### Python Version Matrix

| Version | `importlib.reload` | `frame.f_code` assign | `frame.f_locals` proxy | Net capability |
|---------|-------------------|-----------------------|------------------------|---------------|
| 3.9–3.11 | Yes | Read-only | No (`ctypes` write-back) | Reload + future-call rebinding only |
| 3.12 | Yes | **Writable** | No (`ctypes` write-back) | Full: reload + current-frame code swap |
| 3.13+ | Yes | Writable | **Yes** (PEP 667) | Full: reload + native locals proxy |

The adapter degrades gracefully: on older runtimes, `updateFrameCode`
and `rebindFrameLocals` do less work and emit explanatory warnings.

### DAP Client Compatibility

Clients that do not understand `dapper/hotReload` simply never send the
request.  The `supportsHotReload` capability flag gates the feature.

The standard `loadedSource` event is emitted regardless, so any
DAP-conforming client that tracks loaded sources will see the refresh.

The custom `dapper/hotReloadResult` event is silently ignored by clients
that do not register for it (per DAP spec §"Custom events").

---

## File Manifest

### New types to add to `protocol/requests.py`

| TypedDict | Purpose |
|-----------|---------|
| `HotReloadOptions` | Per-request behaviour overrides |
| `HotReloadArguments` | Request arguments |
| `HotReloadRequest` | Full request envelope |
| `HotReloadResponseBody` | Success response body |
| `HotReloadResponse` | Full response envelope |
| `HotReloadResultEventBody` | Custom event body |
| `HotReloadResultEvent` | Full event envelope |

### Modifications to existing files

| File | Change |
|------|--------|
| `protocol/capabilities.py` | Add `supportsHotReload: NotRequired[bool]` to `Capabilities` |
| `adapter/request_handlers.py` | Import new types; add `_handle_dapper_hot_reload()` handler; add `"supportsHotReload": True` to `_handle_initialize` body |
| `adapter/payload_extractor.py` | Register `"dapper/hotReloadResult"` extractor in `_EXTRACTORS` |

---

## Rejected Alternatives

### A. Use standard `restart` request

The `restart` request terminates the session and asks the client to
relaunch.  This loses all runtime state (breakpoints, variable watches,
call stack position).  Hot reload specifically preserves state.

### B. Use `evaluate` to call `importlib.reload()` directly

This works for the naive case but:
- Skips breakpoint re-synchronisation (breakpoints stop working).
- Skips frame-eval cache invalidation (stale bytecode traps).
- Provides no structured feedback or diagnostics.
- Cannot rebind frame locals or patch `f_code`.

A dedicated request encapsulates all of these coordination steps.

### C. Non-namespaced command name (e.g. `hotReload`)

DAP reserves un-namespaced commands for the specification itself.
Adapter-specific extensions should use a `<prefix>/` namespace to
avoid collisions with future DAP versions.

### D. File-watcher–triggered automatic reload

Automatic reload on file save is a UX feature, not a protocol concern.
It can be implemented in the VS Code extension by watching
`workspace.onDidSaveTextDocument` and sending the `dapper/hotReload`
request — no protocol changes needed beyond what this DEP defines.

### E. Batch reload (multiple modules in one request)

Deferred to a future DEP.  Single-module reload covers the common case
(edit one file, reload it).  Batch semantics (ordering, partial failure,
transactional rollback) add significant complexity.  The request can be
sent multiple times for multi-file edits.

---

## Open Questions

1. **Should `rebindFrameLocals` default to `True` or `False`?**
   Currently proposed as `True` (maximise usefulness).  Counter-argument:
   `False` is safer and more predictable for a first release; upgrade to
   `True` after field testing.

2. **Should the adapter support reloading packages (`__init__.py`)?**
   `importlib.reload` supports this, but the semantics are different
   (sub-modules are *not* reloaded).  This DEP does not prohibit it,
   but the implementation plan may choose to warn or restrict.

3. **Should the response include a diff of changed functions?**
   Useful for UX but expensive to compute.  Deferred — could be added as
   optional fields in a later revision of `HotReloadResponseBody`.

---

## References

- [DAP Specification — Custom Messages](https://microsoft.github.io/debug-adapter-protocol/specification#Custom_messages)
- [CPython `importlib.reload`](https://docs.python.org/3/library/importlib.html#importlib.reload)
- [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/) (Python 3.13 `frame.f_locals` proxy)
- [CPython `frame.f_code` writeability](https://github.com/python/cpython/issues/91153) (added in 3.12)
- `dapper/protocol/data_breakpoints.py` — existing pattern for a self-contained protocol extension module

---

*DEP-001 Draft — 2026-02-21*
