# Frame Evaluation Optimization Implementation Guide

This document provides a detailed roadmap for implementing frame evaluation optimizations in the Dapper debugger, inspired by debugpy's approach to achieve zero-overhead debugging.

## Overview

The goal is to implement Cython-based frame evaluation to minimize the performance overhead of Python's `sys.settrace()` mechanism by:

1. **Selective Frame Tracing**: Only enable tracing on frames that actually have breakpoints
2. **Bytecode Modification**: Directly inject breakpoint code into function bytecode
3. **Caching Mechanisms**: Store breakpoint information in code objects to avoid recomputation
4. **Fast Path Optimizations**: Skip debugger frames and use C-level hooks

## Implementation Tasks

### Phase 1: Foundation (High Priority)

#### 1. Research Current Architecture
**Objective**: Understand Dapper's existing debugging mechanism
**Tasks**:
- Analyze `dapper/debug_launcher.py` and `dapper/debugger_bdb.py` for current tracing implementation
- Document how breakpoints are currently handled
- Identify integration points for frame evaluation
- Study the in-process vs subprocess mode differences

**Deliverables**: Architecture analysis document with current tracing flow diagram

#### 2. Feasibility Study
**Objective**: Assess viability of frame evaluation in Dapper's context
**Tasks**:
- Evaluate compatibility with Dapper's async/sync hybrid architecture
- Analyze impact on existing IPC mechanisms
- Assess Python version compatibility requirements
- Identify potential conflicts with current debugging features

**Deliverables**: Feasibility report with risk assessment and recommendations

#### 3. Setup Cython Build Environment
**Objective**: Establish compilation pipeline for Cython extensions
**Tasks**:
- Add Cython dependency to `pyproject.toml`
- Create `setup.py` or `pyproject.toml` configuration for Cython compilation
- Set up build scripts for development and distribution
- Configure CI/CD pipeline for Cython compilation

**Deliverables**: Working build system that can compile Cython modules

### Phase 2: Core Implementation (Medium Priority)

#### 4. Design Frame Evaluation Module
**Objective**: Create module structure similar to debugpy's approach
**Structure**:
```
dapper/
├── _frame_eval/
│   ├── __init__.py
│   ├── frame_eval_main.py          # Main entry point and configuration
│   ├── frame_evaluator.pyx         # Core Cython implementation
│   ├── frame_eval_cython_wrapper.pyx  # Python/Cython interface
│   ├── frame_tracing.py            # Tracing utilities
│   └── modify_bytecode.py          # Bytecode manipulation
```

**Key Components**:
- `ThreadInfo` class for thread-local data
- `FuncCodeInfo` class for code object caching
- Frame evaluator hook implementation
- Bytecode injection system

#### 5. Implement Core Frame Evaluator
**Objective**: Create the main Cython frame evaluation hook
**Key Functions**:
```cython
cdef PyObject * get_bytecode_while_frame_eval(PyFrameObject * frame_obj, int exc)
cdef ThreadInfo get_thread_info()
cdef FuncCodeInfo get_func_code_info(PyFrameObject * frame_obj, PyCodeObject * code_obj)
```

**Features**:
- Hook into Python's frame evaluation using `_PyEval_EvalFrameDefault`
- Thread-local storage for debugging state
- Recursive protection with `inside_frame_eval` counter
- Fast path for frames without breakpoints

#### 6. Implement Bytecode Modification
**Objective**: Create system for injecting breakpoints into bytecode
**Key Functions**:
```python
def insert_code(code_obj, wrapper_code, line, break_at_lines)
def create_pydev_trace_code_wrapper(line)
def update_globals_dict(globals_dict)
```

**Features**:
- Parse existing bytecode using `dis` module
- Insert breakpoint checks at specific line numbers
- Generate new code objects with injected breakpoints
- Preserve original function semantics

#### 7. Implement Caching System
**Objective**: Store and retrieve breakpoint information efficiently
**Components**:
- Code object caching using `_PyCode_SetExtra`
- Thread-local storage for `ThreadInfo` instances
- File type caching to skip debugger frames
- Breakpoint validity checking with mtime comparison

#### 8. Implement Selective Tracing
**Objective**: Only enable tracing when necessary
**Logic**:
- Check if frame has breakpoints before enabling tracing
- Use bytecode modification for static breakpoints
- Fall back to tracing for dynamic conditions (step commands, exceptions)
- Skip pydevd/dapper internal frames entirely

### Phase 3: Integration (Medium Priority)

#### 9. Integrate with Dapper Debugger
**Objective**: Connect frame evaluation to existing Dapper components
**Integration Points**:
- Modify `PyDebugger` class to support frame evaluation mode
- Update `DebuggerBDB` to work with new tracing mechanism
- Adapt IPC protocols for frame evaluation status
- Ensure compatibility with both in-process and subprocess modes

**Configuration**:
- Add `useFrameEval: boolean` option to DAP launch request
- Implement fallback to traditional tracing when frame eval fails
- Add environment variable support for development

#### 10. Add Configuration Options
**Objective**: Provide user control over frame evaluation
**Options**:
- DAP launch request parameter
- Environment variables (`DAPPER_USE_FRAME_EVAL`)
- Runtime enable/disable capability
- Debugging/verbose mode for troubleshooting

#### 11. Implement Compatibility Checks
**Objective**: Handle edge cases and platform differences
**Checks**:
- Python version compatibility (3.6-3.10 for frame eval)
- gevent compatibility detection
- Stackless Python handling
- IPython compatible debugging conflicts

### Phase 4: Testing & Documentation (Medium/Low Priority)

#### 12. Create Comprehensive Tests
**Test Categories**:
- Unit tests for individual components
- Integration tests with Dapper debugger
- Performance benchmarks
- Compatibility tests across Python versions
- Edge case testing (gevent, threading, etc.)

**Performance Benchmarks**:
- Measure overhead of traditional vs frame evaluation
- Test with various breakpoint densities
- Memory usage profiling
- Startup time comparisons

#### 13. Document Implementation ✅ COMPLETED
**Documentation Tasks**:
- ✅ Update ARCHITECTURE.md with frame evaluation details
- ✅ Create user guide for enabling frame evaluation
- ✅ Document performance characteristics  
- ✅ Add troubleshooting guide for common issues

**Created Documents**:
- [ARCHITECTURE.md](ARCHITECTURE.md) - Updated with comprehensive frame evaluation architecture
- [FRAME_EVAL_USER_GUIDE.md](FRAME_EVAL_USER_GUIDE.md) - Complete user guide with configuration examples
- [FRAME_EVAL_PERFORMANCE.md](FRAME_EVAL_PERFORMANCE.md) - Detailed performance characteristics and benchmarks
- [FRAME_EVAL_TROUBLESHOOTING.md](FRAME_EVAL_TROUBLESHOOTING.md) - Comprehensive troubleshooting guide
- [README.md](README.md) - Updated to reference frame evaluation documentation

#### 14. Performance Benchmarks
**Benchmark Suite**:
- Micro-benchmarks for frame evaluation overhead
- Real-world debugging scenario performance
- Memory usage analysis
- Scalability testing with multiple threads/processes

## Technical Considerations

### Memory Management
- Use proper reference counting with `Py_INCREF`/`Py_DECREF`
- Handle code object lifecycle carefully
- Prevent memory leaks in thread-local storage

### Thread Safety
- Ensure thread-local data is properly isolated
- Handle race conditions in breakpoint cache updates
- Protect shared data structures with appropriate locks

### Error Handling
- Graceful fallback when frame evaluation fails
- Proper cleanup on process shutdown
- Comprehensive error logging and reporting

### Performance Optimization
- Minimize Python/C boundary crossings
- Use efficient data structures (cdef classes)
- Optimize hot paths in frame evaluation
- Profile and optimize critical sections

## Success Criteria

1. **Performance**: 10x+ speed improvement for debugging with no breakpoints
2. **Compatibility**: Maintain full backward compatibility with existing Dapper features
3. **Reliability**: Robust error handling and graceful fallbacks
4. **Maintainability**: Clean, well-documented code that integrates seamlessly
5. **Test Coverage**: Comprehensive test suite with performance validation

## Timeline Estimate

- **Phase 1**: 2-3 weeks (research and setup)
- **Phase 2**: 4-6 weeks (core implementation)
- **Phase 3**: 3-4 weeks (integration and configuration)
- **Phase 4**: 2-3 weeks (testing and documentation)

**Total Estimated Time**: 11-16 weeks

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cython build complexity | High | Start with simple build setup, incrementally add complexity |
| Compatibility with async architecture | Medium | Thorough testing in both in-process and subprocess modes |
| Performance regression in some scenarios | Medium | Comprehensive benchmarking and fallback mechanisms |
| Maintenance overhead | Low | Clear documentation and modular design |

## Next Steps

1. Begin with Phase 1 research tasks
2. Set up development environment with Cython
3. Create proof-of-concept for basic frame evaluation hook
4. Iterate based on feasibility study results
