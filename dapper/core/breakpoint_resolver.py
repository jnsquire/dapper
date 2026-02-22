"""BreakpointResolver: Unified evaluation of breakpoint conditions, hit counts, and log messages.

This module consolidates the common logic for evaluating whether a breakpoint
should cause execution to stop, including:
- Condition expressions (evaluated in frame context)
- Hit conditions (e.g., ">=5", "%3", "==10")
- Log messages (logpoints that emit output instead of stopping)

The resolver is breakpoint-type agnostic and can be used for line breakpoints,
function breakpoints, data breakpoints, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from enum import auto
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

from dapper.core.debug_utils import evaluate_hit_condition
from dapper.core.debug_utils import format_log_message
from dapper.shared.value_conversion import evaluate_with_policy

if TYPE_CHECKING:
    import types

logger = logging.getLogger(__name__)


class ResolveAction(Enum):
    """The action to take after resolving a breakpoint."""

    STOP = auto()  # Stop execution at this breakpoint
    CONTINUE = auto()  # Continue execution (condition not met or log message emitted)
    SKIP = auto()  # No breakpoint applies here


@dataclass
class BreakpointMeta:
    """Metadata for a breakpoint that controls its behavior.

    Attributes:
        condition: Python expression that must evaluate to True to stop.
        hit_condition: Expression controlling when to stop based on hit count
                       (e.g., ">=5", "%3", "==10", or just "5").
        log_message: If set, emit this message instead of stopping. Supports
                     {expression} interpolation in the frame context.
        hit_count: Current number of times this breakpoint has been hit.
    """

    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None
    hit_count: int = 0

    def increment_hit(self) -> int:
        """Increment and return the new hit count."""
        self.hit_count += 1
        return self.hit_count


class OutputEmitter(Protocol):
    """Protocol for emitting output (e.g., from logpoints)."""

    def __call__(self, category: str, output: str) -> None:
        """Emit output with the given category."""
        ...


@dataclass
class ResolveResult:
    """Result of resolving a breakpoint.

    Attributes:
        action: The action to take (STOP, CONTINUE, or SKIP).
        reason: Human-readable reason for the action (useful for debugging).
        log_output: If action is CONTINUE due to a logpoint, the rendered message.
    """

    action: ResolveAction
    reason: str = ""
    log_output: str | None = None

    @property
    def should_stop(self) -> bool:
        """Convenience property to check if execution should stop."""
        return self.action == ResolveAction.STOP

    @property
    def should_continue(self) -> bool:
        """Convenience property to check if execution should continue."""
        return self.action == ResolveAction.CONTINUE


class BreakpointResolver:
    """Evaluates breakpoint conditions and determines whether to stop.

    This class encapsulates the common logic for all breakpoint types:
    1. Increment hit counter
    2. Evaluate hit condition (if any)
    3. Evaluate condition expression (if any)
    4. Handle log messages (logpoints)

    Example usage:
        resolver = BreakpointResolver()

        # For a line breakpoint
        meta = BreakpointMeta(condition="x > 5", hit_condition=">=3")
        result = resolver.resolve(meta, frame)
        if result.should_stop:
            # Break execution
            ...

        # For a logpoint
        meta = BreakpointMeta(log_message="Value of x: {x}")
        result = resolver.resolve(meta, frame, emit_output=my_emitter)
        # result.action will be CONTINUE, and output was emitted
    """

    def resolve(
        self,
        meta: BreakpointMeta | dict[str, Any] | None,
        frame: types.FrameType | None = None,
        *,
        emit_output: OutputEmitter | None = None,
        auto_increment_hit: bool = True,
    ) -> ResolveResult:
        """Evaluate a breakpoint and determine the appropriate action.

        Args:
            meta: Breakpoint metadata (BreakpointMeta or dict with compatible keys).
                  If None, returns STOP (no conditions to check).
                  If a dict is passed, the 'hit' key will be updated in place.
            frame: The execution frame for evaluating conditions and log messages.
                   Required if condition or log_message contains expressions.
            emit_output: Callback to emit log output. If not provided and a log
                         message is present, the message is rendered but not emitted.
            auto_increment_hit: If True, increment the hit counter before evaluation.

        Returns:
            ResolveResult indicating the action to take.
        """
        if meta is None:
            return ResolveResult(ResolveAction.STOP, reason="no conditions")

        # Track original dict for hit count writeback
        original_dict: dict[str, Any] | None = None
        if isinstance(meta, dict):
            original_dict = meta
            meta = self._meta_from_dict(meta)

        # Step 1: Increment hit count
        if auto_increment_hit:
            meta.increment_hit()
            # Write back to original dict if provided
            if original_dict is not None:
                original_dict["hit"] = meta.hit_count

        # Step 2: Check hit condition
        if meta.hit_condition and not evaluate_hit_condition(meta.hit_condition, meta.hit_count):
            return ResolveResult(
                ResolveAction.CONTINUE,
                reason=f"hit condition not met: {meta.hit_condition} (count={meta.hit_count})",
            )

        # Step 3: Check condition expression
        if meta.condition:
            condition_result = self._evaluate_condition(meta.condition, frame)
            if not condition_result:
                return ResolveResult(
                    ResolveAction.CONTINUE,
                    reason=f"condition not met: {meta.condition}",
                )

        # Step 4: Handle log message (logpoint)
        if meta.log_message:
            rendered = self._render_log_message(meta.log_message, frame)
            if emit_output is not None:
                emit_output("console", rendered)
            return ResolveResult(
                ResolveAction.CONTINUE,
                reason="logpoint",
                log_output=rendered,
            )

        # All conditions passed, stop execution
        return ResolveResult(ResolveAction.STOP, reason="conditions met")

    def should_stop(
        self,
        meta: BreakpointMeta | dict[str, Any] | None,
        frame: types.FrameType | None = None,
        *,
        emit_output: OutputEmitter | None = None,
    ) -> bool:
        """Convenience method that returns True if execution should stop.

        This is equivalent to `resolve(...).should_stop` but more concise
        for simple use cases.
        """
        return self.resolve(meta, frame, emit_output=emit_output).should_stop

    def _meta_from_dict(self, d: dict[str, Any]) -> BreakpointMeta:
        """Convert a dict to BreakpointMeta, handling DAP-style key names."""
        return BreakpointMeta(
            condition=d.get("condition"),
            hit_condition=d.get("hitCondition") or d.get("hit_condition"),
            log_message=d.get("logMessage") or d.get("log_message"),
            hit_count=int(d.get("hit", 0) or d.get("hit_count", 0)),
        )

    def _evaluate_condition(
        self,
        condition: str,
        frame: types.FrameType | None,
    ) -> bool:
        """Evaluate a condition expression in the frame context.

        Returns True if the condition is met, False otherwise.
        On evaluation error, returns False (condition not met).
        """
        if frame is None:
            logger.debug("Cannot evaluate condition without frame: %s", condition)
            return False

        try:
            result = evaluate_with_policy(condition, frame, allow_builtins=True)
            return bool(result)
        except Exception as e:
            logger.debug("Condition evaluation failed: %s (%s)", condition, e)
            return False

    def _render_log_message(
        self,
        template: str,
        frame: types.FrameType | None,
    ) -> str:
        """Render a log message template with frame variable interpolation.

        Supports {expression} syntax where expression is evaluated in frame context.
        """
        if frame is None:
            return template

        try:
            return format_log_message(template, frame)
        except Exception as e:
            logger.debug("Log message rendering failed: %s (%s)", template, e)
            return template


# Module-level singleton for convenience
_default_resolver: BreakpointResolver | None = None


def get_resolver() -> BreakpointResolver:
    """Get the default BreakpointResolver instance."""
    global _default_resolver  # noqa: PLW0603
    if _default_resolver is None:
        _default_resolver = BreakpointResolver()
    return _default_resolver


__all__ = [
    "BreakpointMeta",
    "BreakpointResolver",
    "OutputEmitter",
    "ResolveAction",
    "ResolveResult",
    "get_resolver",
]
