# Dapper — Code Quality & Architecture Improvement Checklist

Prioritised list of improvements identified through a full codebase review.
Items are grouped into tiers; work each tier roughly top-to-bottom.

---

## P1 — Architecture & Design

- [ ] **Decompose `PyDebugger` (989 lines, 50+ methods)**
      The class is a God Object that owns threading, IPC, breakpoints, process 
      management, event routing and session state. The manager sub-objects 
      (`_event_router`, `_lifecycle_manager`, …) are a step in the right 
      direction — move `PyDebugger` itself into `dapper/adapter/debugger/` and 
      thin out the remaining facade to pure delegation.
      _File: [dapper/adapter/server.py](../dapper/adapter/server.py)_

- [ ] **Eliminate duplicated dispatch + standalone methods in `ExternalProcessBackend`**
      Every DAP command is implemented twice — once in `_dispatch_*` and again as
      a direct method. Unify to a single implementation.
      _File: [dapper/adapter/external_backend.py](../dapper/adapter/external_backend.py)_

- [ ] **Remove `InProcessBackend.exception_info` deep attribute chain**
      `self._bridge._inproc.debugger.exception_handler.exception_info_by_thread`
      violates every layer boundary. Expose a proper method on the bridge instead.
      _File: [dapper/adapter/inprocess_backend.py](../dapper/adapter/inprocess_backend.py)_

- [ ] **Break circular reference between `PyDebugger` ↔ `DebugAdapterServer`**
      They hold references to each other at construction time. Introduce an
      interface / Protocol so neither depends on the concrete class.
      _Files: [server.py](../dapper/adapter/server.py), [server_core.py](../dapper/adapter/server_core.py)_

- [ ] **Consolidate the two IPC management systems**
      `IPCContext` (539 lines) and `IPCManager` (210 lines) overlap
      significantly. Pick one and remove the other, or merge into a single
      coherent abstraction.
      _Files: [dapper/ipc/ipc_context.py](../dapper/ipc/ipc_context.py), [dapper/ipc/ipc_manager.py](../dapper/ipc/ipc_manager.py)_

- [ ] **Rename `server.py` → `debugger.py` (or move `PyDebugger` into `adapter/debugger/`)**
      The file contains `PyDebugger`, not a server. The actual server is
      `server_core.py`. The `__getattr__` re-export at the bottom of `server.py`
      is an extra source of confusion.
      _File: [dapper/adapter/server.py](../dapper/adapter/server.py)_

- [ ] **Replace string-based exception classification with `isinstance` checks**
      `error_patterns.py` classifies errors by substring-matching on the message
      (`"connection"`, `"pipe"`, `"timeout"`). Use `isinstance(e, (ConnectionError,
      BrokenPipeError, TimeoutError, …))` instead.
      _File: [dapper/errors/error_patterns.py](../dapper/errors/error_patterns.py#L88-L103)_

---

## P2 — Duplication & DRY

- [ ] **Define `SafeSendDebugMessageFn` Protocol once**
      Currently copy-pasted **8 times** across `dapper/shared/` handler modules.
      Define it in `command_handler_helpers.py` and import everywhere.

- [ ] **Define `Payload = dict[str, Any]` type alias once**
      Redefined in **8 files** under `dapper/shared/`. Consolidate.

- [ ] **Extract `_normalize_continue_payload` to `BaseBackend`**
      Identical static method in `ExternalProcessBackend` and
      `InProcessBackend`.

- [ ] **Unify sync/async error decorator logic in `error_patterns.py`**
      `handle_adapter_errors` and `async_handle_adapter_errors` (and the
      `*_backend_errors` pair) share ~160 lines of identical classification
      logic. Factor the classifier into a shared function.
      _File: [dapper/errors/error_patterns.py](../dapper/errors/error_patterns.py)_

- [ ] **Remove `dapper/launcher/comm.py`**
      It only re-exports `send_debug_message` from `dapper.shared.debug_shared`.
      Callers can import directly.

---

## P3 — Build, CI & Packaging

- [ ] **Consolidate all metadata into `pyproject.toml`; slim down `setup.py`**
      `setup.py` should only drive the Cython extension build. Remove the
      duplicate `version`, `install_requires`, `extras_require`, `classifiers`,
      etc. Also remove dead dev-deps `black`, `isort`, `mypy`.
      _File: [setup.py](../setup.py)_

- [ ] **Re-enable Pyright in CI**
      Type-checking is disabled (`if: false`) in `.github/workflows/ci.yml`.
      Fix the blocking issues and turn it back on so type regressions are caught.
      _File: [.github/workflows/ci.yml](../.github/workflows/ci.yml#L96-L98)_

- [ ] **Unify Python version matrices across CI workflows**
      `ci.yml` tests `[3.11, 3.13]`; `tests.yml` tests `[3.9–3.12]`.
      Neither covers the full supported range. Merge into one matrix or align.

- [ ] **Add macOS to the Python test matrix**
      Only Ubuntu and Windows are tested. The project claims OS-independent.

---

## P4 — Type Safety & Annotations

- [ ] **Add type annotations to untyped `frame` parameters**
      Multiple functions in `debug_utils.py` and `debugger_bdb.py` take a
      `frame` argument with no annotation (should be `types.FrameType`).

- [ ] **Replace `Any` constructor params in `ExternalProcessBackend`**
      `get_process_state: Any`, `lock: Any`, `get_next_command_id: Any` should
      be proper `Callable[…]` types.

- [ ] **Narrow `debugger: Any` in `BreakpointsController` / `SteppingController`**
      Use the existing `DebuggerLike` Protocol or a narrower one.

- [ ] **Reduce excessive `cast()` usage**
      Especially in `request_handlers.py`, `inprocess_backend.py`, and
      `external_backend.py`. Prefer returning properly typed objects from
      helpers instead of casting.

- [ ] **Widen `DebuggerLike` Protocol to cover methods accessed via `getattr`**
      `command_handlers.py` accesses `set_break`, `clear_break`, etc. through
      `getattr` yet these aren't on the Protocol — the type checker can't verify
      correctness.

---

## P5 — Error Handling

- [ ] **Narrow `except Exception` to expected types**
      Several broad catches should be `ImportError`, `KeyError`, etc.:
      - `debugger_bdb.py` L37 (should be `ImportError`)
      - `inprocess_debugger.py` L95 (swallows breakpoint-clear errors)
      - `data_breakpoint_state.py` L127 (swallows comparison errors)

- [ ] **Make error-handling decorator usage consistent in `RequestHandler`**
      Some handlers use `@async_handle_adapter_errors`, most use manual
      `try`/`except`. Pick one approach.

- [ ] **Use lazy `%s` formatting in logger calls**
      Multiple files use `f"…{e}"` with `logger.warning`; switch to
      `logger.warning("… %s", e)`.
      _Files: base_backend.py, external_backend.py, inprocess_backend.py_

- [ ] **Log (or raise) unknown kwargs in `config_manager.update_config`**
      Currently any unrecognized key is silently ignored.
      _File: [dapper/config/config_manager.py](../dapper/config/config_manager.py#L48-L63)_

---

## P6 — Code Hygiene & Dead Code

- [ ] **Move test constants out of `dapper/common/constants.py`**
      `TEST_DEFAULT_LINE`, `TEST_ALT_LINE_*`, `TEST_STRING_LIMIT`,
      `DEFAULT_BREAKPOINT_LINE`, etc. are test fixtures, not production
      constants. Move to a `tests/constants.py` or test conftest.
      _File: [dapper/common/constants.py](../dapper/common/constants.py#L28-L33)_

- [ ] **Remove `TYPE_CHECKING: Final[bool] = False` from `constants.py`**
      It's never used — real code imports `TYPE_CHECKING` from `typing`.

- [ ] **Implement or remove empty cleanup callbacks**
      `ExternalProcessBackend._cleanup_ipc` and
      `InProcessBackend._cleanup_bridge` are `pass` stubs registered as
      callbacks that never do anything.

- [ ] **Remove legacy `thread_count` / `thread_ids` in `ThreadTracker`**
      Marked "legacy" and never meaningfully used.

- [ ] **Replace `globals()["_current_config"]` with `global _current_config`**
      In `config_manager._assign_current_config` — the `globals()` pattern is
      unnecessarily obscure.

- [ ] **Remove duplicate `Coroutine` import in `error_patterns.py`**
      Imported twice at L18 and L35.

- [ ] **Remove dead `black`/`isort` deps and stale `flake8` config**
      The project uses `ruff`; `setup.cfg [flake8]` and `pyproject.toml
      [tool.flake8]` sections are unused.

---

## P7 — Test Quality

- [ ] **Add dedicated tests for untested modules**
      At least: `ipc_manager.py`, `reader_helpers.py`, `error_patterns.py`,
      `stack_handlers.py`, `variable_command_runtime.py`,
      `payload_extractor.py`, `breakpoint_handlers.py`.

- [ ] **Add `tests/functional/__init__.py`**
      Missing `__init__.py` can cause import issues in some pytest
      configurations.

- [ ] **Remove global monkey-patch of `asyncio.new_event_loop` at import time**
      `tests/conftest.py` L19–21 patches at module level; convert to a
      session-scoped fixture.

- [ ] **Refactor `FakeDebugger` (480 lines) in `tests/mocks.py`**
      Consider splitting into smaller focused fakes or fixture factories so
      changes don't cascade across unrelated tests.

---

## P8 — Minor / Low-Priority

- [ ] **Remove hardcoded default port 4711 in `TCPServerConnection`**
      Require explicit port configuration or use OS-assigned (`port=0`).

- [ ] **Replace camelCase handler names with snake_case**
      `_handle_configurationDone`, `_handle_setVariable`, etc. use camelCase
      with `# noqa: N802` suppressions. The dispatcher already converts case —
      rename to `_handle_configuration_done` etc.

- [ ] **Collapse `ProtocolHandler` proxy into `ProtocolFactory`**
      `ProtocolHandler` delegates every method 1:1 — either merge or inherit.

- [ ] **Remove `variable_command_runtime.py` indirection layer**
      Functions are trivial pass-throughs adding no value.

- [ ] **Consider `__getattr__` delegation on `InProcessBridge`**
      15+ one-line pass-through methods could be replaced with attribute
      delegation, keeping only the event-isolation logic explicit.

- [ ] **Clean up `config_manager.update_config`**
      Replace the 3 hard-coded `if` checks with a generic field-update loop
      (or use `dataclasses.replace`).

---

*Generated: 2026-02-16 — based on review of all modules, tests, CI config, and packaging files.*
