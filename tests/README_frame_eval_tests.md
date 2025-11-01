# Frame Evaluation Tests

This directory contains comprehensive tests for the frame evaluation system in Dapper.

## Test Files

### Core Component Tests

1. **`test_frame_eval_integration.py`**
   - Tests for `DebuggerFrameEvalBridge` class
   - Configuration management
   - Statistics collection and monitoring
   - Global function interfaces
   - Error handling and fallback behavior

2. **`test_selective_tracer.py`**
   - Tests for `TraceManager`, `FrameAnalyzer`, and `TraceDispatcher` classes
   - Breakpoint detection and frame analysis
   - Selective tracing logic
   - Thread safety for concurrent operations
   - Performance characteristics

3. **`test_cache_manager.py`**
   - Tests for `CacheManager`, `ThreadInfo`, and `FuncCodeInfo` classes
   - Thread-local storage management
   - Code object caching
   - File type detection and caching
   - Memory usage and performance

4. **`test_frame_eval_integration_mock.py`**
   - Integration tests with mock debugger instances
   - Mock `DebuggerBDB` and `PyDebugger` classes
   - End-to-end integration scenarios
   - Multi-debugger integration
   - Performance and error recovery testing

## Test Categories

### Unit Tests
- Individual class and method testing
- Mock-based isolation testing
- Edge case and error condition testing

### Integration Tests
- Component interaction testing
- Mock debugger integration
- Configuration and lifecycle testing

### Performance Tests
- Cache efficiency measurement
- Trace call overhead analysis
- Memory usage validation
- Concurrent operation performance

### Thread Safety Tests
- Multi-threaded access patterns
- Race condition detection
- Thread-local storage validation

## Running Tests

### Run All Frame Evaluation Tests
```bash
pytest tests/test_frame_eval_*.py -v
```

### Run Specific Test Categories
```bash
# Core integration tests
pytest tests/test_frame_eval_integration.py -v

# Selective tracer tests
pytest tests/test_selective_tracer.py -v

# Cache manager tests
pytest tests/test_cache_manager.py -v

# Mock integration tests
pytest tests/test_frame_eval_integration_mock.py -v
```

### Run Performance Tests
```bash
pytest tests/ -k "performance" -v
```

### Run Thread Safety Tests
```bash
pytest tests/ -k "thread" -v
```

## Test Coverage

The test suite covers:

- **Configuration Management**: All configuration options and their effects
- **Statistics Collection**: Performance metrics and integration statistics
- **Breakpoint Handling**: Static and dynamic breakpoint detection
- **Selective Tracing**: Frame analysis and tracing decisions
- **Caching System**: Thread info, code info, and file type caching
- **Error Handling**: Fallback mechanisms and error recovery
- **Integration Points**: DebuggerBDB and PyDebugger integration
- **Performance**: Overhead measurement and optimization validation
- **Thread Safety**: Concurrent access and race condition prevention

## Mock Classes

### MockDebuggerBDB
Simulates the DebuggerBDB class with:
- `user_line` method call tracking
- Breakpoint management
- Integration lifecycle support

### MockPyDebugger
Simulates the PyDebugger class with:
- `set_breakpoints` method call tracking
- Trace function management
- Thread and breakpoint storage

## Test Data and Fixtures

Tests use various mock objects and fixtures:
- Mock frame objects with configurable properties
- Mock code objects for testing caching
- Temporary file creation for file-based tests
- Thread management for concurrent testing

## Expected Test Results

When running correctly, the test suite should:
- Pass all unit tests with proper mocking
- Validate integration behavior with mock debuggers
- Confirm performance characteristics meet requirements
- Verify thread safety under concurrent load
- Test error handling and recovery mechanisms

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure the frame evaluation modules are in the Python path
2. **Mock Failures**: Check that mock objects have the expected attributes
3. **Thread Test Flakiness**: Some thread tests may need timing adjustments
4. **File System Tests**: Ensure proper permissions for temporary file creation

### Debugging Test Failures

Use pytest's verbose output and debugging features:
```bash
pytest tests/test_frame_eval_integration.py -v -s --tb=short
```

For specific test debugging:
```bash
pytest tests/test_frame_eval_integration.py::TestDebuggerFrameEvalBridge::test_initialization -v -s
```

## Contributing

When adding new tests:
1. Follow the existing naming conventions
2. Use appropriate mock objects for isolation
3. Include both positive and negative test cases
4. Add performance assertions where relevant
5. Document complex test scenarios
6. Ensure thread safety for concurrent operations

## Test Dependencies

- `pytest`: Test framework
- `unittest.mock`: Mock object creation
- Standard library: `threading`, `time`, `os`, `sys`
- Dapper frame evaluation modules (under test)
