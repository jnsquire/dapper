# Frame Evaluation Troubleshooting Guide

This guide helps diagnose and resolve common issues with Dapper's frame evaluation system.

## Quick Diagnosis

### Health Check Script

Use this script to quickly check frame evaluation health:

```python
#!/usr/bin/env python3
"""Frame evaluation health check"""

import sys
import traceback
from dapper._frame_eval.debugger_integration import (
    DebuggerFrameEvalBridge, 
    get_integration_statistics
)

def health_check():
    """Perform comprehensive health check"""
    print("🔍 Frame Evaluation Health Check")
    print("=" * 50)
    
    # Check 1: Module imports
    try:
        from dapper._frame_eval._frame_evaluator import (
            frame_eval_func, stop_frame_eval, get_thread_info
        )
        print("✅ Core modules imported successfully")
    except ImportError as e:
        print(f"❌ Core module import failed: {e}")
        return False
    
    # Check 2: Cython compilation
    try:
        thread_info = get_thread_info()
        print(f"✅ Cython functions working: {type(thread_info).__name__}")
    except Exception as e:
        print(f"❌ Cython functions failed: {e}")
        return False
    
    # Check 3: Integration bridge
    try:
        bridge = DebuggerFrameEvalBridge()
        print("✅ Integration bridge created")
    except Exception as e:
        print(f"❌ Integration bridge failed: {e}")
        return False
    
    # Check 4: Statistics
    try:
        stats = get_integration_statistics()
        print(f"✅ Statistics available: {len(stats)} sections")
    except Exception as e:
        print(f"❌ Statistics failed: {e}")
        return False
    
    # Check 5: Frame evaluation activation
    try:
        frame_eval_func()
        stats = get_integration_statistics()
        if stats['config']['enabled']:
            print("✅ Frame evaluation activated successfully")
        else:
            print("⚠️ Frame evaluation not enabled")
    except Exception as e:
        print(f"❌ Frame evaluation activation failed: {e}")
        return False
    
    print("\n🎉 All health checks passed!")
    return True

if __name__ == "__main__":
    success = health_check()
    sys.exit(0 if success else 1)
```

## Common Issues

### 1. Frame Evaluation Not Working

#### Symptoms
- No performance improvement
- High tracing overhead
- Breakpoints not triggering efficiently

#### Diagnosis
```python
from dapper._frame_eval.debugger_integration import get_integration_statistics

def diagnose_not_working():
    stats = get_integration_statistics()
    
    print("Diagnosis:")
    print(f"  Enabled: {stats['config']['enabled']}")
    print(f"  Integrations: {stats['integration_stats']['integrations_enabled']}")
    print(f"  Errors: {stats['integration_stats']['errors_handled']}")
    
    if not stats['config']['enabled']:
        print("❌ Frame evaluation is disabled")
    elif stats['integration_stats']['errors_handled'] > 0:
        print("❌ Errors detected, check logs")
    elif stats['integration_stats']['integrations_enabled'] == 0:
        print("❌ No integrations active")
    else:
        print("✅ Frame evaluation appears to be working")

diagnose_not_working()
```

#### Solutions

**Enable Frame Evaluation**
```python
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Method 1: Auto-integrate
bridge = DebuggerFrameEvalBridge()
bridge.auto_integrate_debugger(debugger_instance)

# Method 2: Manual integration
from dapper._frame_eval._frame_evaluator import frame_eval_func
frame_eval_func()
```

**Check Configuration**
```python
config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'fallback_on_error': True
}
bridge = DebuggerFrameEvalBridge(config)
```

**Verify Breakpoints**
```python
# Frame evaluation only helps with breakpoints exist
if not debugger.get_breakpoints():
    print("⚠️ No breakpoints set - frame evaluation won't show improvement")
```

### 2. High Memory Usage

#### Symptoms
- Memory usage increases significantly
- System becomes slow or unresponsive
- Out-of-memory errors

#### Diagnosis
```python
from dapper._frame_eval.cache_manager import get_cache_manager_stats

def diagnose_memory():
    try:
        cache_stats = get_cache_manager_stats()
        print(f"Cache entries: {cache_stats['total_entries']}")
        print(f"Cache memory: {cache_stats['memory_usage_mb']:.1f}MB")
        
        if cache_stats['total_entries'] > 1000:
            print("⚠️ Large cache size detected")
        if cache_stats['memory_usage_mb'] > 50:
            print("⚠️ High memory usage detected")
    except Exception as e:
        print(f"❌ Cache stats unavailable: {e}")

diagnose_memory()
```

#### Solutions

**Reduce Cache Size**
```python
config = {
    'cache_enabled': True,
    'max_cache_size': 500,  # Reduce from default 1000
    'cache_ttl': 60         # Clear cache after 1 minute
}
```

**Disable Caching**
```python
config = {
    'cache_enabled': False,
    'bytecode_optimization': False  # Also reduces memory
}
```

**Monitor Memory Usage**
```python
import psutil
import os

def monitor_memory():
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    
    print(f"Current memory usage: {memory_mb:.1f}MB")
    
    if memory_mb > 200:  # 200MB threshold
        print("⚠️ High memory usage - consider reducing cache size")

monitor_memory()
```

### 3. Compatibility Issues

#### Symptoms
- Crashes or segmentation faults
- Strange debugging behavior
- Breakpoints not working correctly

#### Diagnosis
```python
import sys
import platform

def diagnose_compatibility():
    print("System Information:")
    print(f"  Python version: {sys.version}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Architecture: {platform.architecture()}")
    
    # Check for known problematic configurations
    if sys.version_info < (3, 9):
        print("❌ Python < 3.9 not supported")
    elif sys.version_info >= (3, 14):
        print("⚠️ Python 3.14+ not tested")
    
    # Check for problematic modules
    problematic_modules = ['gevent', 'eventlet', 'greenlet']
    for module in problematic_modules:
        if module in sys.modules:
            print(f"⚠️ {module} detected - may cause issues")

diagnose_compatibility()
```

#### Solutions

**Enable Fallback Mode**
```python
config = {
    'enabled': True,
    'fallback_on_error': True,
    'bytecode_optimization': False,  # Safer
    'selective_tracing': True
}
```

**Disable Problematic Features**
```python
# Conservative configuration for compatibility
safe_config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': False,
    'cache_enabled': False,
    'performance_monitoring': False,
    'fallback_on_error': True
}
```

**Use Traditional Tracing**
```python
# Fall back to traditional tracing if issues persist
config = {'enabled': False}
```

### 4. Performance Regression

#### Symptoms
- Frame evaluation slower than traditional tracing
- Performance degrades over time
- High CPU usage

#### Diagnosis
```python
import time
from dapper._frame_eval.debugger_integration import get_integration_statistics

def benchmark_performance(duration=10):
    """Benchmark frame evaluation performance"""
    start_stats = get_integration_statistics()
    start_time = time.time()
    
    # Run your debugged code here
    your_debugged_function()
    
    end_time = time.time()
    end_stats = get_integration_statistics()
    
    duration = end_time - start_time
    trace_calls = end_stats['performance_data']['trace_function_calls']
    frame_evals = end_stats['performance_data']['frame_eval_calls']
    
    print(f"Duration: {duration:.2f}s")
    print(f"Trace calls: {trace_calls}")
    print(f"Frame evals: {frame_evals}")
    print(f"Calls per second: {trace_calls / duration:.0f}")
    
    if trace_calls / duration < 1000:
        print("⚠️ Low call rate - may indicate performance issues")

benchmark_performance()
```

#### Solutions

**Optimize Configuration**
```python
# High-performance configuration
perf_config = {
    'enabled': True,
    'selective_tracing': True,
    'bytecode_optimization': True,
    'cache_enabled': True,
    'performance_monitoring': False,  # Reduce overhead
    'trace_overhead_threshold': 0.05
}
```

**Clear Cache**
```python
from dapper._frame_eval.cache_manager import clear_all_caches

clear_all_caches()
print("✅ Caches cleared")
```

**Restart Frame Evaluation**
```python
from dapper._frame_eval._frame_evaluator import stop_frame_eval, frame_eval_func

# Restart frame evaluation system
stop_frame_eval()
frame_eval_func()
```

### 5. Integration Issues

#### Symptoms
- Frame evaluation not integrating with debugger
- Breakpoints not being optimized
- Statistics not updating

#### Diagnosis
```python
from dapper._frame_eval.debugger_integration import (
    DebuggerFrameEvalBridge, 
    get_integration_statistics
)

def diagnose_integration():
    try:
        # Check bridge status
        bridge = DebuggerFrameEvalBridge()
        print(f"Bridge created: {bridge is not None}")
        
        # Check statistics
        stats = get_integration_statistics()
        print(f"Integrations enabled: {stats['integration_stats']['integrations_enabled']}")
        print(f"Breakpoints optimized: {stats['integration_stats']['breakpoints_optimized']}")
        
        if stats['integration_stats']['integrations_enabled'] == 0:
            print("❌ No debugger integrations active")
        
    except Exception as e:
        print(f"❌ Integration diagnosis failed: {e}")
        traceback.print_exc()

diagnose_integration()
```

#### Solutions

**Manual Integration**
```python
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Create bridge and integrate manually
bridge = DebuggerFrameEvalBridge()

# For BDB-based debuggers
bridge.integrate_debugger_bdb(debugger_instance)

# For PyDebugger
bridge.integrate_py_debugger(debugger_instance)
```

**Check Debugger Type**
```python
def detect_debugger_type(debugger):
    """Detect debugger type for proper integration"""
    debugger_type = type(debugger).__name__
    
    if debugger_type == 'DebuggerBDB':
        print("Detected BDB-based debugger")
        return 'bdb'
    elif debugger_type == 'PyDebugger':
        print("Detected PyDebugger")
        return 'pydebugger'
    else:
        print(f"Unknown debugger type: {debugger_type}")
        return 'unknown'

debugger_type = detect_debugger_type(debugger_instance)
```

## Advanced Troubleshooting

### Debug Logging

Enable comprehensive debug logging:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable frame evaluation logging
logger = logging.getLogger('dapper._frame_eval')
logger.setLevel(logging.DEBUG)

# Enable performance logging
perf_logger = logging.getLogger('dapper._frame_eval.performance')
perf_logger.setLevel(logging.DEBUG)
```

### Performance Profiling

Profile frame evaluation to identify bottlenecks:

```python
import cProfile
import pstats
from dapper._frame_eval._frame_evaluator import should_trace_frame

def profile_frame_evaluation():
    """Profile frame evaluation performance"""
    profiler = cProfile.Profile()
    
    profiler.enable()
    
    # Profile frame evaluation
    for i in range(10000):
        frame = get_current_frame()  # Your frame here
        should_trace_frame(frame)
    
    profiler.disable()
    
    # Analyze results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(20)

profile_frame_evaluation()
```

### Memory Profiling

Profile memory usage to identify leaks:

```python
import tracemalloc
from dapper._frame_eval.cache_manager import get_cache_manager_stats

def profile_memory():
    """Profile memory usage"""
    tracemalloc.start()
    
    # Run your debugged code
    your_debugged_function()
    
    # Get memory statistics
    current, peak = tracemalloc.get_traced_memory()
    print(f"Current memory: {current / 1024 / 1024:.1f}MB")
    print(f"Peak memory: {peak / 1024 / 1024:.1f}MB")
    
    # Get top memory allocations
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    
    print("\nTop memory allocations:")
    for stat in top_stats[:10]:
        print(f"{stat.size / 1024:.1f}KB: {stat.traceback.format()[-1]}")
    
    tracemalloc.stop()

profile_memory()
```

## Environment-Specific Issues

### IDE Integration

#### VS Code Issues

**Symptoms**: Frame evaluation not working in VS Code debugging

**Solutions**:
```json
{
    "name": "Python: Dapper with Frame Evaluation",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "frameEval": true,
    "frameEvalConfig": {
        "enabled": true,
        "selective_tracing": true,
        "fallback_on_error": true
    }
}
```

#### PyCharm Issues

**Symptoms**: Frame evaluation not working with PyCharm debugger

**Solutions**:
```python
# In your debug configuration
import dapper.debugger
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Enable frame evaluation before starting debugger
bridge = DebuggerFrameEvalBridge()
bridge.auto_integrate_debugger(dapper.debugger)

# Start debugging
dapper.debugger.start()
```

### Container/VM Issues

#### Docker Issues

**Symptoms**: Frame evaluation failing in Docker containers

**Diagnosis**:
```bash
# Check if Cython extensions are built
python -c "from dapper._frame_eval._frame_evaluator import get_thread_info; print('OK')"
```

**Solutions**:
```dockerfile
# Ensure build dependencies are installed
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Build Cython extensions during container build
RUN python setup.py build_ext --inplace
```

#### Virtual Environment Issues

**Symptoms**: Import errors or missing Cython extensions

**Solutions**:
```bash
# Rebuild Cython extensions in virtual environment
pip install -e .
python setup.py build_ext --inplace

# Verify installation
python -c "from dapper._frame_eval._frame_evaluator import frame_eval_func; print('OK')"
```

## Getting Help

### Collect Diagnostic Information

When reporting issues, collect this information:

```python
#!/usr/bin/env python3
"""Collect diagnostic information for support"""

import sys
import platform
import traceback
from dapper._frame_eval.debugger_integration import get_integration_statistics

def collect_diagnostics():
    """Collect comprehensive diagnostic information"""
    diagnostics = {
        'system': {
            'python_version': sys.version,
            'platform': platform.platform(),
            'architecture': platform.architecture(),
        },
        'frame_eval': {},
        'errors': []
    }
    
    try:
        # Collect frame evaluation statistics
        stats = get_integration_statistics()
        diagnostics['frame_eval'] = stats
        
    except Exception as e:
        diagnostics['errors'].append(f"Statistics collection failed: {e}")
        traceback.print_exc()
    
    try:
        # Test core functionality
        from dapper._frame_eval._frame_evaluator import (
            frame_eval_func, get_thread_info
        )
        
        thread_info = get_thread_info()
        diagnostics['thread_info'] = str(type(thread_info))
        
    except Exception as e:
        diagnostics['errors'].append(f"Core functionality test failed: {e}")
        traceback.print_exc()
    
    return diagnostics

def print_diagnostics():
    """Print diagnostic information"""
    diagnostics = collect_diagnostics()
    
    print("🔍 Diagnostic Information")
    print("=" * 50)
    
    print("\nSystem Information:")
    for key, value in diagnostics['system'].items():
        print(f"  {key}: {value}")
    
    print("\nFrame Evaluation Status:")
    if diagnostics['frame_eval']:
        stats = diagnostics['frame_eval']
        print(f"  Enabled: {stats['config']['enabled']}")
        print(f"  Integrations: {stats['integration_stats']['integrations_enabled']}")
        print(f"  Breakpoints optimized: {stats['integration_stats']['breakpoints_optimized']}")
    else:
        print("  ❌ No statistics available")
    
    if diagnostics['errors']:
        print("\nErrors:")
        for error in diagnostics['errors']:
            print(f"  ❌ {error}")
    
    print("\n📋 Please include this information when reporting issues")

if __name__ == "__main__":
    print_diagnostics()
```

### Support Resources

1. **Documentation**: 
   - [Frame Evaluation Implementation](FRAME_EVAL_IMPLEMENTATION.md)
   - [User Guide](FRAME_EVAL_USER_GUIDE.md)
   - [Performance Characteristics](FRAME_EVAL_PERFORMANCE.md)

2. **Community Support**:
   - GitHub Issues: Report bugs and request features
   - Discussions: Ask questions and share experiences

3. **Debug Information**:
   - Enable debug logging: `logging.getLogger('dapper._frame_eval').setLevel(logging.DEBUG)`
   - Use diagnostic script above
   - Include performance statistics and error traces

## Quick Fixes Summary

| Issue | Quick Fix |
|-------|-----------|
| Not working | Check `enabled: True` in config |
| High memory | Reduce `max_cache_size` or disable caching |
| Compatibility issues | Set `fallback_on_error: True` |
| Performance regression | Clear cache and restart frame eval |
| Integration problems | Use manual integration methods |

For persistent issues, use the diagnostic script and collect detailed information before seeking support.
