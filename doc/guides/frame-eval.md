<!-- Frame evaluation user guide — merged from doc/getting-started/frame-eval/index.md and doc/getting-started/frame-eval/troubleshooting.md -->
# Frame Evaluation — User Guide

This guide explains how to enable and use Dapper's frame evaluation system for high-performance debugging.

## Overview

Frame evaluation is an optimization that replaces traditional line-by-line tracing with selective evaluation that only intervenes when breakpoints are present. This can reduce debugging overhead by 60-80% while maintaining full debugging functionality.

## Current Support

The frame-eval subsystem now has a real `eval_frame` backend on supported CPython builds.

- `tracing` remains the safest default family and uses `sys.settrace` or `sys.monitoring`.
- `eval_frame` installs a CPython eval-frame callback and, for selected frames, temporarily enables a scoped trace function only for the target code object.
- Runtime status now reports the selected backend and low-level hook status.
- Hook statistics now expose slow-path activations and live return/exception event counts.

Current limitation: the eval-frame backend still relies on scoped tracing for debugger event delivery once a frame is selected. It does not yet switch between original and modified code objects at frame-entry time.

## Quick Start

### Basic Usage

```python
# Method 1: Enable via launch configuration
{
    "command": "launch",
    "arguments": {
        "program": "${workspaceFolder}/your_script.py",
        "frameEval": true  # Enable frame evaluation
    }
}

# Method 2: Enable programmatically
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Auto-integrate with existing debugger
bridge = DebuggerFrameEvalBridge()
bridge.auto_integrate_debugger(debugger_instance)
```

### VS Code Configuration

Add to your `launch.json`:

```json
{
    "name": "Python: Dapper with Frame Evaluation",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "console": "integratedTerminal",
    "frameEval": true,
    "frameEvalConfig": {
        "backend": "auto",
        "tracing_backend": "auto",
        "enabled": true,
        "fallback_to_tracing": true,
        "conditional_breakpoints_enabled": true
    }
}
```

## Configuration Options

### Core Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | false | Enable or disable frame evaluation |
| `backend` | string | `auto` | Select `auto`, `tracing`, or `eval_frame` |
| `tracing_backend` | string | `auto` | Select `auto`, `settrace`, or `sys_monitoring` when tracing is used |
| `fallback_to_tracing` | bool | true | Fall back to tracing if eval-frame is unavailable or rejected |
| `debug` | bool | false | Enable extra frame-eval diagnostics |
| `cache_size` | int | 1000 | Maximum cache size for frame-eval helpers |
| `optimize` | bool | true | Enable frame-eval optimizations |
| `timeout` | float | 30.0 | Runtime timeout budget for frame-eval operations |
| `conditional_breakpoints_enabled` | bool | true | Evaluate conditional breakpoints before dispatch when supported |
| `condition_budget_s` | float | 0.1 | Soft wall-clock budget for a single conditional breakpoint evaluation |

### Advanced Configuration

#### Backend Selection

The frame evaluation subsystem currently supports two backend families:

* **tracing** — uses the traditional ``sys.settrace`` or ``sys.monitoring``
  APIs.  This is the default and is guaranteed to work on all supported
  interpreters.
* **eval_frame** — a CPython eval-frame hook that selects frames at entry and
    installs a scoped trace function only for the matching code object. This
    backend is available only on supported CPython builds.

Backend configuration is controlled with two keys in the config object:

```json
{
    "backend": "auto",            // one of "auto", "tracing", "eval_frame"
    "tracing_backend": "auto"     // existing setting for tracing family
}
```

The `auto` backend mode prefers `eval_frame` when the compatibility policy
reports the interpreter has the necessary support; otherwise it falls back to
the tracing family. The tracing backend key still controls which tracing
implementation is chosen when `backend` is `auto` or `tracing`.

### Verifying The Active Backend

Use runtime status and hook stats to confirm that eval-frame is actually active:

```python
from dapper._frame_eval.frame_eval_main import frame_eval_manager

debug_info = frame_eval_manager.get_debug_info()
runtime_status = debug_info["runtime_status"]

print("backend:", runtime_status.backend_type)
print("hook installed:", runtime_status.hook_installed)
```

For hook-level counters:

```python
from dapper._frame_eval.runtime import FrameEvalRuntime

runtime = FrameEvalRuntime()
stats = runtime.get_stats()
print(stats.hook_stats)
```

Useful hook counters include:

- `slow_path_attempts`
- `slow_path_activations`
- `scoped_trace_installs`
- `return_events`
- `exception_events`

If `backend_type` is not `EvalFrameBackend` or `hook_installed` is `False`, the process is not currently running through the eval-frame backend.

Manager configuration example:


```python
# Advanced manager/runtime configuration
config = {
    'enabled': True,
    'backend': 'eval_frame',
    'tracing_backend': 'auto',
    'fallback_to_tracing': True,
    'conditional_breakpoints_enabled': True,
    'condition_budget_s': 0.1,
}

from dapper._frame_eval.frame_eval_main import frame_eval_manager

frame_eval_manager.setup_frame_eval(config)
```

## Performance Characteristics

### Expected Improvements

- **Tracing Overhead**: 60-80% reduction compared to traditional tracing
- **Memory Usage**: ~10MB additional for typical debugging sessions
- **Startup Time**: <50ms additional initialization
- **Breakpoint Density**: Optimal with <100 breakpoints per file

### Performance Monitoring

Enable performance monitoring to see actual improvements:

```python
from dapper._frame_eval.debugger_integration import get_integration_statistics

# Get performance statistics
stats = get_integration_statistics()
print(f"Trace calls saved: {stats['integration_stats']['trace_calls_saved']}")
print(f"Breakpoints optimized: {stats['integration_stats']['breakpoints_optimized']}")
```

### Telemetry and Selective Tracing

Dapper now exposes structured telemetry for the frame-eval subsystem and richer selective-tracing diagnostics so you can observe fallback/events and tune runtime behavior.

- Telemetry records reason-codes (fallbacks, optimization failures, policy disables) and a short recent-event log.
- Selective tracing exposes lightweight analysis stats (trace-rate, cache-hits, fast-path hits) so you can verify that only relevant frames are being traced.

Minimal example — read/reset telemetry and check selective-tracing stats:

```python
from dapper._frame_eval.telemetry import (
    get_frame_eval_telemetry,
    reset_frame_eval_telemetry,
)
from dapper._frame_eval.debugger_integration import get_integration_statistics

# Read telemetry snapshot
telemetry = get_frame_eval_telemetry()
print(telemetry.reason_counts)

# Reset telemetry collector
reset_frame_eval_telemetry()

# Detect recent bytecode-injection failures
if telemetry.reason_counts.bytecode_injection_failed > 0:
    print("Bytecode injection failures observed — consider disabling bytecode_optimization for troubleshooting")

# Selective-tracing stats are available via integration/runtime stats
stats = get_integration_statistics()
print("trace stats:", stats["trace_stats"])
```

## Usage Patterns

### Best Practices

1. **Enable Early**: Activate frame evaluation before setting breakpoints
2. **Monitor Performance**: Use performance monitoring to verify improvements
3. **Fallback Gracefully**: Let the system fall back to traditional tracing when needed
4. **Cache Management**: Enable caching for the best performance

### Known Limitations

1. The current eval-frame backend still delivers debugger events through scoped tracing after the frame is selected.
2. Breakpoint activation is currently based on executable lines known at frame entry, so the backend may register all executable lines in a function even when the debugger ultimately stops on only one line.
3. Bytecode-modified code-object selection at eval-frame entry is still a roadmap item. Code-extra-backed modified-code caching and invalidation are now implemented, but the hook still executes the original frame and relies on scoped tracing for delivery.

### Common Scenarios

#### Development Debugging
```python
# Enable with conservative settings for development
config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': False,  # Safer for development
    'cache_enabled': True,
    'performance_monitoring': True,
    'fallback_on_error': True
}
```

#### Production Debugging
```python
# Aggressive optimization for production debugging
config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'cache_enabled': True,
    'performance_monitoring': False,  # Minimal overhead
    'fallback_on_error': True
}
```

#### Performance Testing
```python
# Detailed monitoring for performance analysis
config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'cache_enabled': True,
    'performance_monitoring': True,
    'fallback_on_error': True,
    'trace_overhead_threshold': 0.05  # 5% threshold
}
```

## Troubleshooting

### Quick Diagnosis

Use this script to quickly check frame evaluation health:

```python
#!/usr/bin/env python3
"""Frame evaluation health check"""

import sys
from dapper._frame_eval.debugger_integration import (
    DebuggerFrameEvalBridge,
    get_integration_statistics,
)

def health_check():
    """Perform comprehensive health check"""
    print("Frame Evaluation Health Check")
    print("=" * 50)

    # Check 1: Module imports
    try:
        from dapper._frame_eval._frame_evaluator import (
            frame_eval_func, stop_frame_eval, get_thread_info
        )
        print("OK  Core modules imported successfully")
    except ImportError as e:
        print(f"FAIL  Core module import failed: {e}")
        return False

    # Check 2: Cython compilation
    try:
        thread_info = get_thread_info()
        print(f"OK  Cython functions working: {type(thread_info).__name__}")
    except Exception as e:
        print(f"FAIL  Cython functions failed: {e}")
        return False

    # Check 3: Integration bridge
    try:
        bridge = DebuggerFrameEvalBridge()
        print("OK  Integration bridge created")
    except Exception as e:
        print(f"FAIL  Integration bridge failed: {e}")
        return False

    # Check 4: Statistics
    try:
        stats = get_integration_statistics()
        print(f"OK  Statistics available: {len(stats)} sections")
    except Exception as e:
        print(f"FAIL  Statistics failed: {e}")
        return False

    # Check 5: Frame evaluation activation
    try:
        frame_eval_func()
        stats = get_integration_statistics()
        if stats['config']['enabled']:
            print("OK  Frame evaluation activated successfully")
        else:
            print("WARN  Frame evaluation not enabled")
    except Exception as e:
        print(f"FAIL  Frame evaluation activation failed: {e}")
        return False

    print("\nAll health checks passed!")
    return True

if __name__ == "__main__":
    success = health_check()
    sys.exit(0 if success else 1)
```

### Common Issues

#### Frame Evaluation Not Working

**Symptoms**: No performance improvement, high tracing overhead, breakpoints not triggering efficiently.

**Diagnosis**:
```python
from dapper._frame_eval.debugger_integration import get_integration_statistics

def diagnose_not_working():
    stats = get_integration_statistics()

    print("Diagnosis:")
    print(f"  Enabled: {stats['config']['enabled']}")
    print(f"  Integrations: {stats['integration_stats']['integrations_enabled']}")
    print(f"  Errors: {stats['integration_stats']['errors_handled']}")

    if not stats['config']['enabled']:
        print("Frame evaluation is disabled")
    elif stats['integration_stats']['errors_handled'] > 0:
        print("Errors detected, check logs")
    elif stats['integration_stats']['integrations_enabled'] == 0:
        print("No integrations active")
    else:
        print("Frame evaluation appears to be working")

diagnose_not_working()
```

**Solutions**:

1. Verify frame evaluation is enabled:
   ```python
   from dapper._frame_eval.debugger_integration import get_integration_statistics
   stats = get_integration_statistics()
   print(f"Frame eval active: {stats['config']['enabled']}")
   ```

2. Check for errors in integration:
   ```python
   stats = get_integration_statistics()
   if stats['integration_stats']['errors_handled'] > 0:
       print("Frame evaluation errors detected")
   ```

3. Ensure breakpoints are set correctly — frame evaluation only helps when breakpoints exist:
   ```python
   debugger.set_breakpoint('file.py', 10)
   ```

#### High Memory Usage

**Symptoms**: Memory usage increases significantly during debugging.

**Solutions**:

1. Reduce cache size:
   ```python
   config = {'max_cache_size': 500}  # Reduce from default 1000
   ```

2. Enable cache TTL:
   ```python
   config = {'cache_ttl': 60}  # Clear cache after 1 minute
   ```

3. Monitor cache statistics:
   ```python
   from dapper._frame_eval.cache_manager import get_cache_manager_stats
   cache_stats = get_cache_manager_stats()
   print(f"Cache size: {cache_stats['total_entries']}")
   ```

#### Compatibility Issues

**Symptoms**: Crashes, strange behavior, or debugging not working as expected.

**Solutions**:

1. Enable fallback mode:
   ```python
   config = {'fallback_on_error': True}
   ```

2. Disable bytecode optimization:
   ```python
   config = {'bytecode_optimization': False}
   ```

3. Revert to traditional tracing entirely:
   ```python
   config = {'enabled': False}
   ```

### Debug Information

Enable detailed logging to troubleshoot issues:

```python
import logging
logging.getLogger('dapper._frame_eval').setLevel(logging.DEBUG)

# Enable performance monitoring
config = {'performance_monitoring': True}
```

### Performance Analysis

Use the built-in performance analysis tools:

```python
from dapper._frame_eval.debugger_integration import get_integration_statistics

def analyze_performance():
    stats = get_integration_statistics()

    print("Frame Evaluation Performance Analysis")
    print("=" * 50)
    print(f"Enabled: {stats['config']['enabled']}")
    print(f"Integrations: {stats['integration_stats']['integrations_enabled']}")
    print(f"Breakpoints Optimized: {stats['integration_stats']['breakpoints_optimized']}")
    print(f"Trace Calls Saved: {stats['integration_stats']['trace_calls_saved']}")
    print(f"Errors Handled: {stats['integration_stats']['errors_handled']}")

    if stats['performance_data']:
        perf = stats['performance_data']
        print(f"Trace Function Calls: {perf['trace_function_calls']}")
        print(f"Frame Eval Calls: {perf['frame_eval_calls']}")

analyze_performance()
```

## See Also

- [Build Guide](../architecture/frame-eval/build-guide.md)
