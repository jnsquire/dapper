# Frame Evaluation User Guide

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

### Common Issues

#### Frame Evaluation Not Working

**Symptoms**: No performance improvement, high tracing overhead

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

3. Ensure breakpoints are set correctly:
   ```python
   # Frame evaluation only helps when breakpoints exist
   debugger.set_breakpoint('file.py', 10)
   ```

#### High Memory Usage

**Symptoms**: Memory usage increases significantly during debugging

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

**Symptoms**: Crashes, strange behavior, or debugging not working

**Solutions**:
1. Enable fallback mode:
   ```python
   config = {'fallback_on_error': True}
   ```

2. Disable bytecode optimization:
   ```python
   config = {'bytecode_optimization': False}
   ```

3. Use traditional tracing:
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

# Run analysis
analyze_performance()
```

## Advanced Topics

### Custom Integration

For advanced use cases, you can integrate frame evaluation manually:

```python
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge
from dapper._frame_eval._frame_evaluator import frame_eval_func, stop_frame_eval

class CustomDebugger:
    def __init__(self):
        self.bridge = DebuggerFrameEvalBridge()
        self.bridge.integrate_debugger_bdb(self)
    
    def start_debugging(self):
        # Enable frame evaluation
        frame_eval_func()
        
        # Set breakpoints
        self.set_breakpoint('app.py', 100)
        
        # Start debugging
        self.run_program()
    
    def stop_debugging(self):
        # Disable frame evaluation
        stop_frame_eval()
        self.bridge.cleanup()

# Usage
debugger = CustomDebugger()
debugger.start_debugging()
```

### Performance Tuning

Fine-tune performance for your specific use case:

```python
# High-performance configuration for large codebases
high_perf_config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'cache_enabled': True,
    'max_cache_size': 2000,  # Larger cache
    'cache_ttl': 600,  # 10 minutes
    'performance_monitoring': False,  # Minimal overhead
    'trace_overhead_threshold': 0.02,  # 2% threshold
    'fallback_on_error': True
}

# Memory-efficient configuration for resource-constrained environments
memory_efficient_config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': False,  # Less memory usage
    'cache_enabled': True,
    'max_cache_size': 100,  # Smaller cache
    'cache_ttl': 60,  # 1 minute
    'performance_monitoring': False,
    'fallback_on_error': True
}
```

## Migration Guide

### From Traditional Tracing

Migrating from traditional tracing to frame evaluation:

1. **Enable Frame Evaluation**:
   ```python
   # Old way
   debugger.set_trace()
   
   # New way
   from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge
   bridge = DebuggerFrameEvalBridge()
   bridge.auto_integrate_debugger(debugger)
   ```

2. **Update Configuration**:
   ```python
   # Add to your existing configuration
   config = debugger.get_config()
   config.update({
       'frameEval': True,
       'frameEvalConfig': {
           'enabled': True,
           'selective_tracing': True
       }
   })
   ```

3. **Monitor Performance**:
   ```python
   # Verify improvements
   stats = get_integration_statistics()
   assert stats['integration_stats']['trace_calls_saved'] > 0
   ```

### Compatibility Considerations

- **Python Versions**: Works with Python 3.9-3.13
- **Third-party Libraries**: Compatible with most libraries including gevent, asyncio
- **Debugging Features**: All standard debugging features work with frame evaluation
- **Performance**: Significant improvements in most scenarios, minimal overhead in edge cases

## Support

If you encounter issues with frame evaluation:

1. Check the [troubleshooting guide](#troubleshooting)
2. Enable debug logging and collect performance statistics
3. File an issue with the following information:
   - Python version
   - Dapper version
   - Configuration used
   - Performance statistics
   - Any error messages or logs

For more information, see the [Frame Evaluation Implementation Details](FRAME_EVAL_IMPLEMENTATION.md) and [Architecture Documentation](ARCHITECTURE.md).
