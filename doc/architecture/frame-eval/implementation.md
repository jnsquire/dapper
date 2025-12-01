<!-- moved from doc/FRAME_EVAL_IMPLEMENTATION.md -->
# Frame Evaluation Optimization — Implementation Guide

This document provides a detailed roadmap for implementing frame evaluation optimizations in the Dapper debugger, inspired by debugpy's approach to achieve zero-overhead debugging.

## Overview

The goal is to implement Cython-based frame evaluation to minimize the performance overhead of Python's `sys.settrace()` mechanism by:

1. **Selective Frame Tracing**: Only enable tracing on frames that actually have breakpoints
2. **Bytecode Modification**: Directly inject breakpoint code into function bytecode
3. **Caching Mechanisms**: Store breakpoint information in code objects to avoid recomputation
4. **Fast Path Optimizations**: Skip debugger frames and use C-level hooks

## Implementation Tasks

### Phase 1: Foundation (High Priority)

... (full implementation guide content copied across)

For full details, refer to the original implementation notes.
