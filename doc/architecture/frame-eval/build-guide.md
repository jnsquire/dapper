<!-- moved from doc/FRAME_EVAL_BUILD_GUIDE.md -->
# Frame Evaluation — Build Guide

This guide explains how to build and test Dapper's Cython frame evaluation extension in development workflows.

## Prerequisites

### Required Dependencies
- **Python 3.9-3.10** (frame evaluation currently targets these versions)
- **Cython >= 3.0**
- **C compiler** (GCC/Clang on Linux/macOS, MSVC on Windows)
- **uv** for project commands and environment management

Install development dependencies:

```bash
uv sync
```

## Build Commands

The repository exposes frame-eval commands through `uv run`:

```bash
# Development build (verbose + Cython annotate enabled)
uv run build-dev

# Production-style build (no annotate)
uv run build-prod

# Clean frame-eval artifacts
uv run frame-eval-clean

# Runtime smoke test for extension availability
uv run frame-eval-test
```

Equivalent script form (still supported):

```bash
uv run python scripts/build_frame_eval.py build-dev
```

## Artifact Layout

Frame-eval build outputs are intentionally isolated under a dedicated artifact tree:

- `build/frame-eval/lib` — built extension modules
- `build/frame-eval/temp` — compiler object/intermediate files
- `build/frame-eval/cython` — generated Cython C/HTML outputs

This avoids leaving compiled `.so`/`.pyd` files inline in `dapper/_frame_eval` during normal development builds.

## Notes

- `uv run build-dev` performs a package reinstall step (`Built dapper @ ...`) before running the extension build; this is expected for script entry points.
- Compiler warnings from generated C code are reduced where practical, but platform/compiler-specific warnings may still appear.
