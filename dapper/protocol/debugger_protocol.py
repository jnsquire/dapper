"""Typing protocol for debugger objects used by handlers and launcher.

This defines the minimal surface used by our command handlers and launcher
so that tests can provide simple dummy implementations without inheriting
from the real DebuggerBDB.
"""

from __future__ import annotations

from typing import Any
from typing import Protocol
from typing import TypedDict
from typing import runtime_checkable


class PresentationHint(TypedDict, total=False):
    kind: str
    attributes: list[str]
    visibility: str


class Variable(TypedDict):
    name: str
    value: str
    type: str
    variablesReference: int
    presentationHint: PresentationHint


class ExceptionDetails(TypedDict):
    """Structured details attached to a captured exception."""

    message: str
    typeName: str
    fullTypeName: str
    source: str
    stackTrace: list[str]


class ExceptionInfo(TypedDict):
    """Top-level structure stored in `current_exception_info` per-thread."""

    exceptionId: str
    description: str
    breakMode: str
    details: ExceptionDetails


class SupportsSteppingController(Protocol):
    """Debugger shape that exposes stepping state through a controller delegate."""

    stepping_controller: Any  # SteppingController-like


class VariableStoreLike(Protocol):
    """Minimum variable-reference store used by shared helpers."""

    next_var_ref: int
    var_refs: dict[int, object]


class SupportsVariableManager(Protocol):
    """Debugger shape that exposes a variable manager delegate."""

    var_manager: VariableStoreLike


class DataBreakpointStateLike(Protocol):
    """Minimal data-breakpoint bookkeeping shape used for hint detection."""

    watch_names: set[str] | list[str] | None
    watch_meta: dict[str, Any] | None
    data_watches: dict[str, Any] | None
    frame_watches: dict[int, list[str]] | None


class SupportsDataBreakpointState(Protocol):
    """Debugger shape that exposes data-breakpoint state via delegate."""

    data_bp_state: DataBreakpointStateLike


class SupportsVariableFactory(Protocol):
    """Debugger shape that can materialize DAP variable payloads."""

    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,
        *,
        max_string_length: int = 1000,
    ) -> Variable: ...


@runtime_checkable
class DebuggerLike(
    SupportsSteppingController,
    SupportsVariableManager,
    SupportsDataBreakpointState,
    SupportsVariableFactory,
    Protocol,
):
    """Public debugger typing surface for shared helpers and command plumbing.

    Intentionally narrow: this protocol models only the capabilities consumed
    by `dapper.shared.debug_shared` and `dapper.shared.command_handlers`.
    """


__all__ = [
    "DataBreakpointStateLike",
    "DebuggerLike",
    "SupportsDataBreakpointState",
    "SupportsSteppingController",
    "SupportsVariableFactory",
    "SupportsVariableManager",
    "VariableStoreLike",
]
