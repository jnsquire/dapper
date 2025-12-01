<!-- Moved from doc/FRAME_EVAL_TROUBLESHOOTING.md -->
# Frame Evaluation — Troubleshooting Guide

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

<!-- rest of file content copied — troubleshooting tips, diagnostics, solutions, etc. -->

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

<!-- file continues with full troubleshooting content -->
