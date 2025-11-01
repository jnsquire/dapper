# Frame Evaluation Build Guide

This guide explains how to build and develop the Cython frame evaluation extensions for Dapper.

## Prerequisites

### Required Dependencies
- **Python 3.9-3.10** (frame evaluation only supported in these versions)
- **Cython >= 3.0**
- **C Compiler** (GCC on Linux/macOS, MSVC on Windows)

### Installing Dependencies
```bash
# Install development dependencies with frame evaluation
pip install -e .[dev,frame-eval]

# Or install manually
pip install Cython>=3.0
```

### Compiler Setup

#### Windows
Install Microsoft Visual Studio Build Tools or Visual Studio Community with C++ development tools.

#### macOS
Install Xcode Command Line Tools:
```bash
xcode-select --install
```

#### Linux
Install build tools:
```bash
# Ubuntu/Debian
sudo apt-get install build-essential python3-dev

# CentOS/RHEL
sudo yum groupinstall "Development Tools"
sudo yum install python3-devel
```

## Build Commands

### Development Build
Build with debug information and annotation files:
```bash
python build_frame_eval.py build-dev
```

This generates:
- Compiled extensions (`.so`/`.pyd`)
- HTML annotation files for debugging Cython code
- Verbose build output

### Production Build
Build optimized extensions:
```bash
python build_frame_eval.py build-prod
```

### Clean Build Artifacts
Remove all build files:
```bash
python build_frame_eval.py clean
```

### Install Development Version
Install in development mode with frame evaluation:
```bash
python build_frame_eval.py install-dev
```

## Manual Build Process

### Using setup.py directly
```bash
# Development build with annotations
CYTHON_ANNOTATE=1 python setup.py build_ext --inplace --verbose

# Production build
python setup.py build_ext --inplace

# Build without frame evaluation
python setup.py build_ext --inplace --no-frame-eval
```

### Using pip
```bash
# Install with frame evaluation
pip install -e .[frame-eval]

# Install without frame evaluation (fallback)
pip install -e .
```

## Directory Structure

```
dapper/
├── _frame_eval/
│   ├── __init__.py              # Python interface
│   ├── _frame_evaluator.pyx     # Core Cython implementation
│   ├── _cython_wrapper.pyx      # Python/Cython interface
│   ├── _frame_evaluator.c       # Generated C code (build output)
│   ├── _cython_wrapper.c        # Generated C code (build output)
│   └── _frame_evaluator.html    # Annotation file (dev build)
└── ...
```

## Configuration Options

### Environment Variables
- `CYTHON_ANNOTATE=1`: Generate HTML annotation files
- `DAPPER_NO_FRAME_EVAL=1`: Skip frame evaluation compilation
- `DISTUTILS_DEBUG=1`: Enable verbose build output

### Build System Features
- **Optional Compilation**: Frame evaluation is optional - Dapper works without it
- **Graceful Fallback**: Automatically falls back to pure Python if Cython unavailable
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Debug Support**: Annotation files for debugging Cython code

## Testing the Build

### Basic Functionality Test
```bash
python build_frame_eval.py test
```

### Manual Testing
```python
from dapper._frame_eval import is_frame_eval_available, enable_frame_eval

print(f"Available: {is_frame_eval_available()}")
if is_frame_eval_available():
    print(f"Enabled: {enable_frame_eval()}")
```

### Integration Testing
```python
# Test with actual debugging
import dapper.debugger_bdb

# Frame evaluation should be automatically used when available
dbg = dapper.debugger_bdb.DebuggerBDB()
# ... debugging operations
```

## Troubleshooting

### Common Issues

#### "Cython not available"
```bash
# Install Cython
pip install Cython>=3.0
```

#### "Microsoft Visual C++ 14.0 is required" (Windows)
Install Visual Studio Build Tools 2019 or later.

#### "Python.h: No such file or directory" (Linux)
Install Python development headers:
```bash
sudo apt-get install python3-dev  # Ubuntu/Debian
sudo yum install python3-devel   # CentOS/RHEL
```

#### Frame evaluation not available
Check Python version - only 3.9-3.10 are supported:
```python
import sys
print(f"Python version: {sys.version_info}")
```

### Debug Build Issues

#### Enable Verbose Output
```bash
DISTUTILS_DEBUG=1 python setup.py build_ext --verbose
```

#### Check Generated C Code
Inspect the generated `.c` files to debug Cython compilation issues.

#### Use Annotation Files
Open the generated `.html` files in a browser to see Cython-to-C mapping.

## Performance Considerations

### Compiler Optimizations
The build system automatically applies optimizations:
- `-O3` on GCC/Clang
- `/O2` on MSVC

### Cython Directives
Applied for maximum performance:
- `boundscheck=False`
- `wraparound=False`
- `initializedcheck=False`
- `cdivision=True`

### Development vs Production
- **Development**: Includes debugging info and annotations
- **Production**: Optimized for speed, smaller binary size

## Continuous Integration

### CI Configuration
```yaml
# Example GitHub Actions step
- name: Install dependencies
  run: |
    pip install Cython>=3.0
    pip install -e .[dev]
    
- name: Build frame evaluation
  run: |
    python build_frame_eval.py build-prod
    
- name: Test frame evaluation
  run: |
    python build_frame_eval.py test
```

### Matrix Testing
Test across:
- Python 3.9, 3.10 (frame evaluation supported)
- Python 3.11+ (fallback to tracing)
- Windows, macOS, Linux

## Distribution

### Source Distribution
Includes `.pyx` files for on-demand compilation.

### Binary Distribution
Includes pre-compiled extensions for common platforms.

### Fallback Behavior
If compilation fails, Dapper gracefully falls back to pure Python tracing.
