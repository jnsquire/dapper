"""
Conditional breakpoint expression evaluator.

Compiles and evaluates user-supplied condition expressions for breakpoints,
providing a fast-path decision before the full debugger trace dispatch.
Expressions are evaluated in the frame's locals + globals context so that
conditions like ``x > 5`` or ``isinstance(result, str)`` work naturally.

Safety properties
-----------------
- Each expression is compiled once and cached by text.
- Evaluation errors (syntax, name, type, …) fall back to ``True`` (trace)
  so that a bad condition never silently skips a breakpoint.
- A wall-clock budget is measured after every evaluation; if it is exceeded
  a telemetry reason code is recorded via
  :meth:`~dapper._frame_eval.telemetry.FrameEvalTelemetry.
  record_selective_tracing_analysis_failed` and the evaluator logs a warning.
  Execution is not interrupted mid-eval because hard thread-level timeouts are
  unsafe inside the trace machinery.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING
from typing import TypedDict

from dapper._frame_eval.telemetry import telemetry

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType


logger = logging.getLogger(__name__)

# Soft timeout: log a warning when a single condition evaluation takes longer
# than this many seconds.  No hard limit is imposed because interrupting
# eval() mid-execution is unsafe inside the trace machinery.
DEFAULT_CONDITION_BUDGET_S: float = 0.1


class CompiledCondition(TypedDict):
    """Cached compiled bytecode for a condition expression.

    Attributes:
        expression: The original source text of the condition.
        code: Compiled code object, or ``None`` when compilation failed.
        compile_error: Error message when compilation failed, otherwise ``None``.
    """

    expression: str
    code: CodeType | None
    compile_error: str | None


class ConditionResult(TypedDict):
    """Result returned by :meth:`ConditionEvaluator.evaluate`.

    Attributes:
        passed: Whether the condition evaluated to a truthy value.
        fallback: ``True`` when the evaluator fell back to *trace* due to an
            error (compilation, runtime, or missing expression).
        error: Human-readable error description, or ``None`` on success.
        elapsed_s: Wall-clock seconds spent evaluating.
    """

    passed: bool
    fallback: bool
    error: str | None
    elapsed_s: float


class ConditionEvaluator:
    """Evaluate per-breakpoint condition expressions in a frame's context.

    This class is thread-safe; it uses a :class:`threading.RLock` around
    the shared compilation cache.

    Args:
        budget_s: Soft wall-clock budget in seconds per evaluation.  When
            exceeded a warning is emitted and a reason code is recorded, but
            the result is still returned rather than discarded.
        enabled: When ``False``, :meth:`evaluate` always returns
            ``passed=True, fallback=False`` without doing any work.
    """

    def __init__(
        self,
        budget_s: float = DEFAULT_CONDITION_BUDGET_S,
        enabled: bool = True,
    ) -> None:
        self._budget_s = budget_s
        self._enabled = enabled
        self._cache: dict[str, CompiledCondition] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether condition evaluation is active."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def evaluate(self, expression: str, frame: FrameType) -> ConditionResult:
        """Evaluate *expression* in *frame*'s local/global context.

        Args:
            expression: Python expression text (e.g. ``"x > 5"``).
            frame: The frame whose ``f_locals`` and ``f_globals`` are used as
                the evaluation namespace.

        Returns:
            :class:`ConditionResult` describing the outcome.  When the
            evaluator is disabled or encounters any error the result has
            ``passed=True`` (safe fallback: always trace).
        """
        if not self._enabled:
            return ConditionResult(passed=True, fallback=True, error=None, elapsed_s=0.0)

        compiled = self._get_compiled(expression)

        if compiled["code"] is None:
            # Compilation failed — conservative fallback: trace the frame.
            return ConditionResult(
                passed=True,
                fallback=True,
                error=compiled["compile_error"],
                elapsed_s=0.0,
            )

        start = time.monotonic()
        try:
            result = bool(eval(compiled["code"], frame.f_globals, frame.f_locals))
        except Exception as exc:
            elapsed = time.monotonic() - start
            error_msg = f"{type(exc).__name__}: {exc}"
            telemetry.record_selective_tracing_analysis_failed(
                expression=expression,
                error=error_msg,
            )
            return ConditionResult(passed=True, fallback=True, error=error_msg, elapsed_s=elapsed)

        elapsed = time.monotonic() - start

        if elapsed > self._budget_s:
            logger.warning(
                "Condition expression %r took %.3fs (budget=%.3fs); "
                "consider simplifying the condition.",
                expression,
                elapsed,
                self._budget_s,
            )
            telemetry.record_selective_tracing_analysis_failed(
                expression=expression,
                reason="budget_exceeded",
                elapsed_s=elapsed,
                budget_s=self._budget_s,
            )

        return ConditionResult(passed=result, fallback=False, error=None, elapsed_s=elapsed)

    def clear_cache(self) -> None:
        """Remove all cached compiled conditions."""
        with self._lock:
            self._cache.clear()

    def cache_size(self) -> int:
        """Number of cached compiled expressions."""
        with self._lock:
            return len(self._cache)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_compiled(self, expression: str) -> CompiledCondition:
        with self._lock:
            if expression in self._cache:
                return self._cache[expression]

        # Compile outside the lock so we don't block other threads.
        try:
            code: CodeType | None = compile(expression, "<breakpoint-condition>", "eval")
            entry: CompiledCondition = {
                "expression": expression,
                "code": code,
                "compile_error": None,
            }
        except SyntaxError as exc:
            error_msg = f"SyntaxError: {exc}"
            logger.debug("Failed to compile breakpoint condition %r: %s", expression, error_msg)
            telemetry.record_selective_tracing_analysis_failed(
                expression=expression,
                error=error_msg,
            )
            entry = {
                "expression": expression,
                "code": None,
                "compile_error": error_msg,
            }

        with self._lock:
            self._cache[expression] = entry
        return entry


# Module-level singleton shared by the selective tracer.
_condition_evaluator = ConditionEvaluator()


def get_condition_evaluator() -> ConditionEvaluator:
    """Return the global :class:`ConditionEvaluator` instance."""
    return _condition_evaluator
