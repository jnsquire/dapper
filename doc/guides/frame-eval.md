<!-- Frame evaluation user guide — merged from doc/getting-started/frame-eval/index.md and doc/getting-started/frame-eval/troubleshooting.md -->
# Frame Evaluation — User Guide

This guide explains how to enable and use Dapper's frame evaluation system for high-performance debugging.

## Overview

Frame evaluation is an optimization that replaces traditional line-by-line tracing with selective evaluation that only intervenes when breakpoints are present. This can reduce debugging overhead by 60-80% while maintaining full debugging functionality.

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
        "selective_tracing": true,
        "bytecode_optimization": true,
        "cache_enabled": true,
        "performance_monitoring": true
    }
}
```

## Configuration Options

### Core Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | true | Enable/disable frame evaluation system |
| `selective_tracing` | bool | true | Only trace frames with breakpoints |
| `bytecode_optimization` | bool | true | Optimize bytecode for faster breakpoint checking |
| `cache_enabled` | bool | true | Enable breakpoint and code object caching |
| `performance_monitoring` | bool | true | Collect performance statistics |
| `fallback_on_error` | bool | true | Fall back to traditional tracing on errors |

### Advanced Configuration

```python
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Advanced configuration
config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'cache_enabled': True,
    'performance_monitoring': True,
    'fallback_on_error': True,
    'max_cache_size': 1000,
    'cache_ttl': 300,  # 5 minutes
    'trace_overhead_threshold': 0.1,  # 10% overhead threshold
}

bridge = DebuggerFrameEvalBridge(config)
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

### Telemetry & selective tracing 🔍

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

- [Implementation Details](../architecture/frame-eval/implementation.md)
- [Performance Architecture](../architecture/frame-eval/performance.md)
- [Build Guide](../architecture/frame-eval/build-guide.md)
