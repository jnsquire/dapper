# Dapper — Code Quality & Architecture Improvement Checklist

Prioritised list of improvements identified through a full codebase review.
Items are grouped into tiers; work each tier roughly top-to-bottom.

---

## P7 — Test Quality

- [x] **Add dedicated tests for untested modules**
      Done: `ipc_manager.py` ✓, `payload_extractor.py` ✓,
      `error_patterns.py` ✓, `stack_handlers.py` ✓,
      `breakpoint_handlers.py` ✓.
      Removed: `reader_helpers.py` (file no longer exists),
      `variable_command_runtime.py` (removed as P8 indirection cleanup).

- [x] **Add `tests/functional/__init__.py`**
      Missing `__init__.py` can cause import issues in some pytest
      configurations.

- [x] **Remove global monkey-patch of `asyncio.new_event_loop` at import time**
      `tests/conftest.py` L19–21 patches at module level; convert to a
      session-scoped fixture.

- [x] **Refactor `FakeDebugger` (480 lines) in `tests/mocks.py`**
      Consider splitting into smaller focused fakes or fixture factories so
      changes don't cascade across unrelated tests.

---

## P8 — Minor / Low-Priority

- [x] **Remove hardcoded default port 4711 in `TCPServerConnection`**
      Require explicit port configuration or use OS-assigned (`port=0`).

- [x] **Replace camelCase handler names with snake_case**
      `_handle_configurationDone`, `_handle_setVariable`, etc. use camelCase
      with `# noqa: N802` suppressions. The dispatcher already converts case —
      rename to `_handle_configuration_done` etc.

- [x] **Collapse `ProtocolHandler` proxy into `ProtocolFactory`**
      `ProtocolHandler` delegates every method 1:1 — either merge or inherit.

- [x] **Remove `variable_command_runtime.py` indirection layer**
      Functions are trivial pass-throughs adding no value.

- [x] **Consider `__getattr__` delegation on `InProcessBridge`**
      15+ one-line pass-through methods could be replaced with attribute
      delegation, keeping only the event-isolation logic explicit.

- [ ] **Clean up `config_manager.update_config`**
      Replace the 3 hard-coded `if` checks with a generic field-update loop
      (or use `dataclasses.replace`).

---

*Generated: 2026-02-16 — based on review of all modules, tests, CI config, and packaging files. Last updated: 2026-02-20 (structured model variable rendering complete; ruff/pyright clean).*
