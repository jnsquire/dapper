# Improvement Ideas for dapper

This document collects actionable suggestions for enhancing the `dapper` codebase, grouped by category.  Use it to track work or convert items into issues/epics.

## Code Quality and Typing

* Remove `# type: ignore` comments by adding missing stubs and tightening signatures.  Consider enabling strict type checking in CI (`pyright`/Pylance `typeCheckingMode = "strict"`).
* Split very large modules (e.g. `reload_helpers.py`) into smaller, single‑responsibility files.
* Resolve remaining `TODO` and `FIXME` notes in code and test assets.
* Add direct test coverage for restart and terminate behaviour in `tests/integration/test_debug_launcher_handlers.py`.
* Run automated refactorings (`source.removeUnusedImports`, `source.addTypeAnnotation`, etc.) to clean up imports and add annotations.
* Exercise or remove code guarded by `# pragma: no cover`; coverage reports show many modules with very low line/branch rates.

## Testing and Coverage

* Add tests for unexercised error paths (e.g. `inprocess_debugger`, `reload_helpers`, IPC cleanup).
* Write integration/unit tests for the VS Code extension and for the Cython frame‑eval functionality.
* Ensure `tests/functional` and `testing/` files are included in CI or removed if obsolete.
## Documentation

* Add a developer guide covering Cython builds, extension development, and the `Docs: serve` task.
* Add docstrings for public API helpers in adapter, IPC, and shared modules to improve both docs and IDE tooling.

## Architecture and Design

* Add an eviction policy to `RuntimeSourceRegistry` to avoid unbounded growth during long sessions.
* Use an LRU or weakref cache for `BytecodeModifier.modified_code_objects` to lower memory footprint.
* Consolidate repeated locking patterns or provide decorators for concurrency safety.
* Define clearer protocols/ABCs for adapter/backend interactions; tests currently patch attributes directly.
* Expose a no‑op telemetry implementation and allow users to disable telemetry more easily.

## Build and Tooling

* Expand pre-commit automation around the existing linting and formatting toolchain.
* Add a `[tool]` section to `pyproject.toml` for dev dependencies and scripts (tests, coverage, docs).
* Enforce static checks and coverage thresholds in CI.
* Clarify the Cython build: ensure wheel packaging, and gracefully fall back to pure‑Python when compilation fails.
* Add tests for the VS Code extension using `vscode-test` and automate its packaging.

## VS Code Extension

* Add telemetry/logging and better error handling for webview failures.
* Provide schema and defaults for configuration settings, plus unit tests for webview message handling.

## Developer Experience

* Add CLI helpers or makefiles for building the extension, running tests, generating coverage, and building docs (many scripts already exist; consolidate them).
* Convert synchronous IPC/adapter code to `async` where it simplifies reasoning.
* Document the developer workflow in the top‑level README.

## Feature Suggestions

* Profile the frame‑eval path to guide further bytecode‑optimization work.
* Add public APIs for registering synthetic sources from other tooling.
* Support additional synthetic filename conventions or provide a stricter matcher.
* Provide a dry‑run mode for bytecode injection to verify success without altering objects.

---

> **Next steps:**
> 1. Triaging – turn these ideas into tracked issues and prioritise by impact.
> 2. Start with tests and typing improvements; they prevent regressions.
> 3. Revisit architecture tweaks once the foundation is solid.

Feel free to iterate on this document or propose additional sections.