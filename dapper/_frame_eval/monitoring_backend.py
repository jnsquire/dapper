"""``sys.monitoring``-based tracing backend (Python 3.12+).

Implements the :class:`~dapper._frame_eval.tracing_backend.TracingBackend`
interface using the :mod:`sys.monitoring` API introduced in :pep:`669` /
CPython 3.12.  When active this backend:

* Claims the :data:`sys.monitoring.DEBUGGER_ID` (0) tool slot so no other
  consumer of that slot can conflict.
* Registers callbacks for ``LINE``, ``CALL``, ``PY_START``, and
  ``PY_RETURN`` events.
* Maintains a per-filename *code-object registry* populated lazily by
  ``PY_START`` events so that ``set_local_events()`` can be called on
  every relevant code object when breakpoints change.
* Uses :func:`sys.monitoring.set_local_events` to enable ``LINE`` events
  *only* for code objects whose source file has active breakpoints,
  keeping non-breakpoint frames at full CPython speed.
* Returns :data:`sys.monitoring.DISABLE` from the ``LINE`` callback for
  any line that is **not** a registered breakpoint, eliminating repeated
  overhead for non-breakpoint lines (one-time cost per offset).
* Evaluates conditional breakpoints via
  :class:`~dapper._frame_eval.condition_evaluator.ConditionEvaluator`.
* Handles ``CALL`` events for *function breakpoints*.
* Supports ``STEP_IN`` / ``STEP_OVER`` / ``STEP_OUT`` / ``CONTINUE``
  semantics via a combination of global and per-code-object event flags.

Thread-safety
-------------
The breakpoint registry and code registry are guarded by ``_lock``
(:class:`threading.RLock`).  Callbacks read from atomically-swapped
immutable snapshots (:class:`frozenset`) so the common hot-path
(``LINE`` returning ``DISABLE``) is effectively lock-free.

Compatibility
-------------
This module imports ``sys.monitoring`` at module level.  On Python < 3.12
the import raises :class:`AttributeError` which is caught by the callers
in :mod:`~dapper._frame_eval.frame_eval_main` — they will fall back to
:class:`~dapper._frame_eval.settrace_backend.SettraceBackend`.
"""

from __future__ import annotations

from collections import defaultdict
import dis
import logging
import sys
import threading
from typing import TYPE_CHECKING
from typing import Any

from dapper._frame_eval.condition_evaluator import ConditionEvaluator
from dapper._frame_eval.tracing_backend import TracingBackend

if TYPE_CHECKING:
    # ``CodeType`` is only used in type annotations; importing at runtime
    # would require the ``types`` module which is always available but the
    # name is only needed for typing.  Placing it in a TYPE_CHECKING block
    # keeps runtime imports minimal and satisfies ruff's TC003 rule.
    from types import CodeType


logger = logging.getLogger(__name__)
_DEBUGGER_BACKLINK_ATTR = "_sys_monitoring_backend"

# ---------------------------------------------------------------------------
# Guard: this module must only be used on Python 3.12+
# ---------------------------------------------------------------------------

if not hasattr(sys, "monitoring"):
    raise ImportError(
        "dapper._frame_eval.monitoring_backend requires Python 3.12+ "
        "(sys.monitoring is not available)",
    )

# Convenience references that stay valid even after class definition.
# ``sys.monitoring`` exists only on Python 3.12+, so the type checker
# cannot guarantee attributes like ``events`` or ``DISABLE``.  Use a
# more specific ignore code rather than blanket ``type: ignore``.
_monitoring = sys.monitoring  # type: ignore[attr-defined]
_events = sys.monitoring.events  # type: ignore[attr-defined]
_DISABLE = sys.monitoring.DISABLE  # type: ignore[attr-defined]

#: Tool identity reserved for debuggers by CPython.
DEBUGGER_ID: int = sys.monitoring.DEBUGGER_ID  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Stepping mode string tokens (matches the rest of the dapper codebase)
# ---------------------------------------------------------------------------
_STEP_IN = "STEP_IN"
_STEP_OVER = "STEP_OVER"
_STEP_OUT = "STEP_OUT"
_CONTINUE = "CONTINUE"


class SysMonitoringBackend(TracingBackend):
    """Tracing backend powered by ``sys.monitoring`` (Python ≥ 3.12).

    See module docstring for a complete feature overview.
    """

    def __init__(self) -> None:
        self._installed: bool = False
        self._debugger: Any = None
        self._lock = threading.RLock()

        # Breakpoints: absolute filename → frozenset of active line numbers.
        # Updated atomically (whole-object replacement) for lock-free reads.
        self._breakpoints: dict[str, frozenset[int]] = {}

        # Conditional expressions: (filename, line) → expression string.
        self._conditions: dict[tuple[str, int], str] = {}

        # Function breakpoint qualified names.
        self._function_breakpoints: frozenset[str] = frozenset()
        self._read_watch_names: frozenset[str] = frozenset()
        self._instruction_map_cache: dict[CodeType, dict[int, tuple[str, Any]]] = {}

        # Code-object registry: filename → set of seen CodeType objects.
        # Populated by _on_py_start; used to apply set_local_events().
        # Protected by _lock; WeakSet upgrade deferred to Phase 4.
        self._code_registry: dict[str, set[CodeType]] = defaultdict(set)

        # Condition evaluator (thread-safe internally).
        self._condition_evaluator = ConditionEvaluator()

        # Stepping state.
        self._step_mode: str = _CONTINUE
        # Code object active when the stepping command was issued — used for
        # STEP_OVER (enable LINE only here) and STEP_OUT (disable LINE here).
        self._step_code: CodeType | None = None

        # Diagnostic counters.
        self._stats: dict[str, int] = {
            "line_callbacks": 0,
            "line_hits": 0,
            "line_disabled": 0,
            "call_callbacks": 0,
            "call_hits": 0,
            "py_start_callbacks": 0,
            "py_return_callbacks": 0,
            "condition_evaluations": 0,
            "condition_skips": 0,
            "instruction_callbacks": 0,
            "instruction_hits": 0,
            "instruction_disabled": 0,
        }

    # ------------------------------------------------------------------
    # TracingBackend — lifecycle (2.1)
    # ------------------------------------------------------------------

    def install(self, debugger_instance: object) -> None:
        """Claim ``DEBUGGER_ID`` and register event callbacks.

        Safe to call on a fresh instance; raises :class:`RuntimeError` if
        the ``DEBUGGER_ID`` slot is already held by another tool.
        """
        with self._lock:
            if self._installed:
                return

            existing = _monitoring.get_tool(DEBUGGER_ID)
            if existing is not None:
                msg = (
                    "sys.monitoring DEBUGGER_ID slot is already held by "
                    f"{existing!r}; SysMonitoringBackend cannot install."
                )
                raise RuntimeError(msg)

            _monitoring.use_tool_id(DEBUGGER_ID, "dapper")

            # Register per-event callbacks.
            _monitoring.register_callback(DEBUGGER_ID, _events.LINE, self._on_line)
            _monitoring.register_callback(DEBUGGER_ID, _events.CALL, self._on_call)
            _monitoring.register_callback(DEBUGGER_ID, _events.PY_START, self._on_py_start)
            _monitoring.register_callback(DEBUGGER_ID, _events.PY_RETURN, self._on_py_return)
            _monitoring.register_callback(
                DEBUGGER_ID,
                _events.INSTRUCTION,
                self._on_instruction,
            )

            # Enable PY_START globally so newly entered functions are
            # discovered and added to the code registry.
            _monitoring.set_events(DEBUGGER_ID, _events.PY_START)

            self._debugger = debugger_instance
            setattr(debugger_instance, _DEBUGGER_BACKLINK_ATTR, self)
            self._installed = True
            self.sync_read_watchpoints()
            logger.debug("SysMonitoringBackend installed (DEBUGGER_ID=%d)", DEBUGGER_ID)

    def shutdown(self) -> None:
        """Release ``DEBUGGER_ID`` and unregister all callbacks."""
        with self._lock:
            if not self._installed:
                return
            debugger = self._debugger
            try:
                _monitoring.set_events(DEBUGGER_ID, _events.NO_EVENTS)
                # unregister all callbacks in one shot; ignore failures
                try:
                    for event in (
                        _events.LINE,
                        _events.CALL,
                        _events.PY_START,
                        _events.PY_RETURN,
                        _events.INSTRUCTION,
                    ):
                        _monitoring.register_callback(DEBUGGER_ID, event, None)
                except Exception:
                    pass
                _monitoring.free_tool_id(DEBUGGER_ID)
            except Exception as exc:
                logger.warning("Error during SysMonitoringBackend.shutdown: %s", exc)
            finally:
                self._installed = False
                self._debugger = None
                self._code_registry.clear()
                self._breakpoints.clear()
                self._conditions.clear()
                self._function_breakpoints = frozenset()
                self._read_watch_names = frozenset()
                self._instruction_map_cache.clear()
                self._step_mode = _CONTINUE
                self._step_code = None
                if (
                    debugger is not None
                    and getattr(
                        debugger,
                        _DEBUGGER_BACKLINK_ATTR,
                        None,
                    )
                    is self
                ):
                    setattr(debugger, _DEBUGGER_BACKLINK_ATTR, None)
        logger.debug("SysMonitoringBackend shut down.")

    # ------------------------------------------------------------------
    # TracingBackend — breakpoints (2.3)
    # ------------------------------------------------------------------

    def update_breakpoints(self, filepath: str, lines: set[int]) -> None:
        """Update line breakpoints for *filepath*.

        Applies ``set_local_events()`` to all code objects known for this
        file, then calls :func:`sys.monitoring.restart_events` so that
        previously ``DISABLE``d offsets will be re-offered.

        Args:
            filepath: Absolute path of the source file.
            lines: Active breakpoint line numbers.  An empty set clears all
                breakpoints for the file.

        """
        with self._lock:
            if lines:
                self._breakpoints[filepath] = frozenset(lines)
            else:
                self._breakpoints.pop(filepath, None)
                # Prune stale per-line conditions.
                for key in [k for k in self._conditions if k[0] == filepath]:
                    del self._conditions[key]

            self._apply_local_events(filepath)

        # restart_events() is a process-global call (affects all tool IDs);
        # call it outside the lock to minimise contention.
        try:
            _monitoring.restart_events()
        except Exception as exc:
            logger.debug("restart_events() failed: %s", exc)

    def sync_read_watchpoints(self) -> None:
        """Sync read-watch names from attached debugger state and refresh event flags."""
        debugger = self._debugger
        state = getattr(debugger, "data_bp_state", None)
        names = getattr(state, "read_watch_names", set()) if state is not None else set()
        normalized = frozenset(name for name in names if isinstance(name, str) and name)

        with self._lock:
            if normalized == self._read_watch_names:
                return
            self._read_watch_names = normalized
            current = _monitoring.get_events(DEBUGGER_ID)
            if normalized:
                _monitoring.set_events(DEBUGGER_ID, current | _events.INSTRUCTION)
            else:
                _monitoring.set_events(DEBUGGER_ID, current & ~_events.INSTRUCTION)

        try:
            _monitoring.restart_events()
        except Exception as exc:
            logger.debug("restart_events() in sync_read_watchpoints failed: %s", exc)

    def set_conditions(self, filepath: str, line: int, expression: str | None) -> None:
        """Register (or clear) a condition expression for a specific line.

        Not part of the :class:`~dapper._frame_eval.tracing_backend.TracingBackend`
        ABC; called by the adapter layer to attach conditional expressions to
        breakpoints.
        """
        with self._lock:
            key = (filepath, line)
            if expression:
                self._conditions[key] = expression
            else:
                self._conditions.pop(key, None)

    def _apply_local_events(self, filepath: str) -> None:
        """Enable / disable ``LINE`` on all code objects for *filepath*.

        Must be called with ``self._lock`` held.
        """
        code_objs = self._code_registry.get(filepath)
        if not code_objs:
            return
        has_bps = filepath in self._breakpoints
        target_events = _events.LINE if has_bps else _events.NO_EVENTS
        # perform the whole loop under one try/except to avoid PERF203
        code = None
        try:
            for code in code_objs:
                _monitoring.set_local_events(DEBUGGER_ID, code, target_events)
        except Exception as exc:
            logger.debug("set_local_events failed for %r: %s", getattr(code, "co_name", None), exc)

    # ------------------------------------------------------------------
    # TracingBackend — stepping (2.5)
    # ------------------------------------------------------------------

    def set_stepping(self, mode: Any) -> None:
        """Configure global event set for the given stepping mode.

        Accepted *mode* strings (case-insensitive):

        ``STEP_IN``
            Enable ``LINE`` globally so every line in every frame fires.
        ``STEP_OVER``
            Enable ``LINE`` only on the *current* code object
            (:meth:`capture_step_context` must have been called beforehand);
            enable ``PY_RETURN`` globally to detect frame exit.
        ``STEP_OUT``
            Disable ``LINE`` on the current code object; enable ``PY_RETURN``
            globally.
        ``CONTINUE`` (or anything else / ``None``)
            Disable global events; re-activate ``LINE`` only for files with
            active breakpoints.
        """
        mode_str = str(mode).upper() if mode is not None else _CONTINUE

        with self._lock:
            self._step_mode = mode_str

            if mode_str == _STEP_IN:
                _monitoring.set_events(
                    DEBUGGER_ID,
                    _events.LINE | _events.PY_START | _events.PY_RETURN,
                )

            elif mode_str == _STEP_OVER:
                _monitoring.set_events(DEBUGGER_ID, _events.PY_START | _events.PY_RETURN)
                if self._step_code is not None:
                    try:
                        _monitoring.set_local_events(DEBUGGER_ID, self._step_code, _events.LINE)
                    except Exception as exc:
                        logger.debug("set_local_events STEP_OVER failed: %s", exc)
                        # Fall back to global LINE so stepping still works.
                        _monitoring.set_events(
                            DEBUGGER_ID,
                            _events.LINE | _events.PY_START | _events.PY_RETURN,
                        )

            elif mode_str == _STEP_OUT:
                _monitoring.set_events(DEBUGGER_ID, _events.PY_START | _events.PY_RETURN)
                if self._step_code is not None:
                    try:
                        _monitoring.set_local_events(
                            DEBUGGER_ID,
                            self._step_code,
                            _events.NO_EVENTS,
                        )
                    except Exception as exc:
                        logger.debug("set_local_events STEP_OUT failed: %s", exc)

            else:  # CONTINUE / unknown
                self._step_mode = _CONTINUE
                self._step_code = None
                # Restore PY_START globally; per-file LINE events only.
                _monitoring.set_events(DEBUGGER_ID, _events.PY_START)
                for fp in list(self._breakpoints):
                    self._apply_local_events(fp)
                try:
                    _monitoring.restart_events()
                except Exception as exc:
                    logger.debug("restart_events() after CONTINUE failed: %s", exc)

    def capture_step_context(self, code: CodeType | None) -> None:
        """Record the code object active when a stepping command is issued.

        Should be called by the debugger immediately *after* invoking
        :meth:`set_stepping` so that ``STEP_OVER`` / ``STEP_OUT`` know
        which code object to watch.
        """
        with self._lock:
            self._step_code = code

    # ------------------------------------------------------------------
    # TracingBackend — exception breakpoints
    # ------------------------------------------------------------------

    def set_exception_breakpoints(self, filters: list[str]) -> None:
        """Configure exception breakpoint filters.

        Exception breakpoints are wired in **Phase 3**; this is a no-op
        placeholder so the :class:`TracingBackend` contract is satisfied.
        """
        # Phase 3: register RAISE / EXCEPTION_HANDLED callbacks here.

    # ------------------------------------------------------------------
    # TracingBackend — statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> dict[str, Any]:
        """Return diagnostic statistics in a shape compatible with
        :class:`~dapper._frame_eval.debugger_integration.IntegrationStatistics`.
        """
        with self._lock:
            return {
                "backend": "SysMonitoringBackend",
                "installed": self._installed,
                "step_mode": self._step_mode,
                "breakpoint_files": len(self._breakpoints),
                "known_code_objects": sum(len(v) for v in self._code_registry.values()),
                "function_breakpoints": len(self._function_breakpoints),
                "counters": dict(self._stats),
                # Keys expected by callers that check IntegrationStatistics shape:
                "config": {
                    "enabled": self._installed,
                    "selective_tracing": True,
                    "bytecode_optimization": False,
                    "cache_enabled": False,
                    "performance_monitoring": True,
                    "fallback_on_error": True,
                },
                "integration_stats": dict(self._stats),
                "performance_data": {},
                "trace_manager_stats": {},
                "cache_stats": {},
                "telemetry": {},
            }

    # ------------------------------------------------------------------
    # Function breakpoints (2.6)
    # ------------------------------------------------------------------

    def update_function_breakpoints(self, names: set[str]) -> None:
        """Set the active function-breakpoint qualified names.

        Not part of the :class:`TracingBackend` ABC; called by the adapter
        layer when the ``setFunctionBreakpoints`` DAP request is received.
        """
        with self._lock:
            self._function_breakpoints = frozenset(names)
            current = _monitoring.get_events(DEBUGGER_ID)
            if names:
                _monitoring.set_events(DEBUGGER_ID, current | _events.CALL)
            # Remove CALL unless stepping requires it.
            elif self._step_mode == _CONTINUE:
                _monitoring.set_events(DEBUGGER_ID, current & ~_events.CALL)

    # ------------------------------------------------------------------
    # sys.monitoring event callbacks (2.2, 2.4, 2.5, 2.6)
    # ------------------------------------------------------------------

    def _on_line(self, code: CodeType, line_number: int) -> object:
        """``LINE`` event callback.

        Called by the CPython evaluation loop just before the instruction
        at *line_number* in *code* is executed.

        Returns :data:`sys.monitoring.DISABLE` when the line is neither a
        registered breakpoint nor covered by an active stepping mode; this
        suppresses future callbacks for the same bytecode offset (one-time
        cost).

        The user frame is ``sys._getframe(1)`` from this callback because
        the evaluation loop (C code) is the immediate Python-level caller.
        """
        self._stats["line_callbacks"] += 1
        filename = code.co_filename

        bp_lines = self._breakpoints.get(filename)
        is_breakpoint_line = bp_lines is not None and line_number in bp_lines
        is_stepping = self._step_mode != _CONTINUE

        if not is_breakpoint_line and not is_stepping:
            self._stats["line_disabled"] += 1
            return _DISABLE

        if is_breakpoint_line:
            # Evaluate condition if present.
            condition = self._conditions.get((filename, line_number))
            if condition is not None:
                self._stats["condition_evaluations"] += 1
                frame = sys._getframe(1)  # noqa: SLF001 - intentional use of private API
                result = self._condition_evaluator.evaluate(condition, frame)
                if not result["passed"] and not result["fallback"]:
                    self._stats["condition_skips"] += 1
                    # Returning DISABLE here would prevent re-evaluation when
                    # the debugger modifies the condition.  Return None instead
                    # so the callback fires again next time.
                    return None

            self._stats["line_hits"] += 1
            frame = sys._getframe(1)  # noqa: SLF001
            debugger = self._debugger
            if debugger is not None and hasattr(debugger, "user_line"):
                try:
                    debugger.user_line(frame)
                except Exception as exc:
                    logger.debug("user_line() raised: %s", exc)
            # Do NOT return DISABLE — breakpoint must remain active.
            return None

        # Stepping path (not a registered breakpoint).
        self._stats["line_hits"] += 1
        frame = sys._getframe(1)  # noqa: SLF001
        debugger = self._debugger
        if debugger is not None and hasattr(debugger, "user_line"):
            try:
                debugger.user_line(frame)
            except Exception as exc:
                logger.debug("user_line() (stepping) raised: %s", exc)
        return None

    def _on_call(
        self,
        _code: CodeType,
        _instruction_offset: int,
        callable_: object,
        arg0: object,
    ) -> object:
        """``CALL`` event callback — function breakpoints (2.6).

        Matches *callable_* against :attr:`_function_breakpoints` by
        ``__qualname__`` (preferred) then ``__name__``.  Returns
        :data:`sys.monitoring.DISABLE` when no match is found.
        """
        self._stats["call_callbacks"] += 1
        fp_names = self._function_breakpoints  # immutable snapshot
        if not fp_names:
            return _DISABLE

        qualname: str | None = getattr(callable_, "__qualname__", None) or getattr(
            callable_,
            "__name__",
            None,
        )
        if qualname in fp_names:
            self._stats["call_hits"] += 1
            frame = sys._getframe(1)  # noqa: SLF001
            debugger = self._debugger
            if debugger is not None and hasattr(debugger, "user_call"):
                try:
                    debugger.user_call(frame, arg0)
                except Exception as exc:
                    logger.debug("user_call() raised: %s", exc)
            return None

        return _DISABLE

    def _on_py_start(self, code: CodeType, _instruction_offset: int) -> object:
        """``PY_START`` callback — code-object registry (2.4).

        Called the first time (per-offset) a frame for *code* is entered.
        Registers *code* in the code registry and optionally enables
        ``LINE`` events for its file.

        Always returns :data:`sys.monitoring.DISABLE` so the VM does not
        call this callback again for the same ``(code, offset)`` pair:
        the code object is now known, so future entries are irrelevant for
        registry purposes.
        """
        self._stats["py_start_callbacks"] += 1
        filename = code.co_filename

        with self._lock:
            self._code_registry[filename].add(code)
            if filename in self._breakpoints:
                try:
                    _monitoring.set_local_events(DEBUGGER_ID, code, _events.LINE)
                except Exception as exc:
                    logger.debug("PY_START set_local_events failed for %r: %s", code.co_name, exc)

        return _DISABLE

    def _on_py_return(self, _code: CodeType, _instruction_offset: int, _retval: object) -> object:
        """``PY_RETURN`` callback — stepping boundary detection (2.5).

        Used for ``STEP_OVER`` and ``STEP_OUT``: when the monitored frame
        returns, we switch to ``STEP_IN`` mode so the next ``LINE`` event
        in the caller fires :meth:`user_line`.
        """
        self._stats["py_return_callbacks"] += 1
        step_mode = self._step_mode

        if step_mode == _CONTINUE:
            return _DISABLE

        if step_mode in (_STEP_OVER, _STEP_OUT):
            with self._lock:
                self._step_mode = _STEP_IN
                self._step_code = None
                _monitoring.set_events(
                    DEBUGGER_ID,
                    _events.LINE | _events.PY_START | _events.PY_RETURN,
                )

        return None

    def _instruction_map_for_code(self, code: CodeType) -> dict[int, tuple[str, Any]]:
        mapping = self._instruction_map_cache.get(code)
        if mapping is not None:
            return mapping

        mapping = {
            instr.offset: (instr.opname, instr.argval) for instr in dis.get_instructions(code)
        }
        self._instruction_map_cache[code] = mapping
        return mapping

    def _on_instruction(self, code: CodeType, instruction_offset: int) -> object:
        """Handle instruction callbacks and stop on watched variable read accesses."""
        self._stats["instruction_callbacks"] += 1

        watched_names = self._read_watch_names
        if not watched_names:
            self._stats["instruction_disabled"] += 1
            return _DISABLE

        op = self._instruction_map_for_code(code).get(instruction_offset)
        if op is None:
            self._stats["instruction_disabled"] += 1
            return _DISABLE

        opname, argval = op
        if opname not in {"LOAD_FAST", "LOAD_NAME", "LOAD_GLOBAL", "LOAD_DEREF"}:
            self._stats["instruction_disabled"] += 1
            return _DISABLE

        if not isinstance(argval, str) or argval not in watched_names:
            self._stats["instruction_disabled"] += 1
            return _DISABLE

        self._stats["instruction_hits"] += 1
        debugger = self._debugger
        if debugger is None or not hasattr(debugger, "handle_read_watch_access"):
            return None

        frame = sys._getframe(1)  # noqa: SLF001
        try:
            debugger.handle_read_watch_access(argval, frame)
        except Exception as exc:
            logger.debug("handle_read_watch_access() raised: %s", exc)
        return None
