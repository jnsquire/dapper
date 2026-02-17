"""Typing protocol for debugger objects used by handlers and launcher.

This defines the minimal surface used by our command handlers and launcher
so that tests can provide simple dummy implementations without inheriting
from the real DebuggerBDB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import TypedDict
from typing import runtime_checkable

# Avoid relying on `TypeAlias` being available in all typing versions; expose
# runtime aliases as simple Any-typed names for static compatibility.

if TYPE_CHECKING:
    import types


class PresentationHint(TypedDict, total=False):
    kind: str
    attributes: list[str]
    visibility: str
    lazy: bool


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


class VariableStoreLike(Protocol):
    """Minimum variable-reference store used by shared helpers."""

    next_var_ref: int
    var_refs: dict[int, object]


class SupportsVariableManager(Protocol):
    """Debugger shape that exposes a variable manager delegate."""

    var_manager: VariableStoreLike


class ThreadTrackerLike(Protocol):
    """Thread/frame tracker surface consumed by stack/stepping/variable handlers."""

    stopped_thread_ids: set[int]
    frames_by_thread: dict[int, list[Any]]
    frame_id_to_frame: dict[int, Any]
    threads: dict[int, Any]

    def build_stack_frames(self, frame: Any) -> list[Any]: ...


class SupportsThreadTracker(Protocol):
    """Debugger shape that exposes thread/frame tracking delegate."""

    thread_tracker: ThreadTrackerLike


class SupportsSteppingCommands(Protocol):
    """Debugger shape that exposes stepping state and commands consumed by handlers."""

    stepping_controller: Any  # supports .stepping and .current_frame

    def set_continue(self) -> None: ...

    def set_next(self, frame: Any) -> None: ...

    def set_step(self) -> None: ...

    def set_return(self, frame: Any) -> None: ...


class BreakpointManagerLike(Protocol):
    """Minimum function-breakpoint storage used by shared handlers."""

    function_names: list[str]
    function_meta: dict[str, dict[str, Any]]


class ExceptionConfigLike(Protocol):
    """Minimum exception-breakpoint flag storage."""

    break_on_raised: bool
    break_on_uncaught: bool


class ExceptionHandlerLike(Protocol):
    """Minimum exception handler shape consumed by shared handlers."""

    config: ExceptionConfigLike
    exception_info_by_thread: dict[int, ExceptionInfo]


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
        frame: types.FrameType | None = None,
        *,
        max_string_length: int = 1000,
    ) -> Variable: ...


class SupportsBreakpointCommands(Protocol):
    """Debugger shape that exposes breakpoint management methods.

    These methods are consumed by ``dapper.shared.breakpoint_handlers`` and
    ``dapper.shared.command_handlers`` to implement the ``setBreakpoints``,
    ``setFunctionBreakpoints``, and ``setExceptionBreakpoints`` DAP commands.
    """

    bp_manager: BreakpointManagerLike
    exception_handler: ExceptionHandlerLike

    def set_break(
        self, filename: str, lineno: int, *, cond: str | None = ..., **kwargs: Any
    ) -> Any: ...

    def clear_break(self, filename: str, lineno: int = ...) -> Any: ...

    def clear_breaks_for_file(self, path: str) -> None: ...

    def clear_break_meta_for_file(self, path: str) -> None: ...

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None: ...

    def clear_all_function_breakpoints(self) -> None: ...


@runtime_checkable
class DebuggerLike(
    SupportsVariableManager,
    SupportsDataBreakpointState,
    SupportsVariableFactory,
    SupportsBreakpointCommands,
    Protocol,
):
    """Public debugger typing surface for shared helpers and command plumbing.

    Covers the capabilities consumed by ``dapper.shared.debug_shared``,
    ``dapper.shared.command_handlers``, and ``dapper.shared.breakpoint_handlers``,
    and maps to the adapter-side ``PyDebugger`` compatibility surface.
    """

    stepping_controller: Any  # stepping/current_frame-compatible delegate

    def run(self, code: str) -> Any: ...

    # VarRef aliases (exposed for tests). Use broad `Any`-typed names so
    # different implementations remain structurally compatible.
    VarRefObject: Any
    VarRefScope: Any
    VarRefList: Any
    VarRef: Any


@runtime_checkable
class CommandHandlerDebuggerLike(
    DebuggerLike,
    SupportsThreadTracker,
    SupportsSteppingCommands,
    Protocol,
):
    """Extended debugger surface consumed by command handler implementations."""

    stack: list[Any] | None


__all__ = [
    "BreakpointManagerLike",
    "CommandHandlerDebuggerLike",
    "DataBreakpointStateLike",
    "DebuggerLike",
    "ExceptionConfigLike",
    "ExceptionHandlerLike",
    "SupportsBreakpointCommands",
    "SupportsDataBreakpointState",
    "SupportsSteppingCommands",
    "SupportsThreadTracker",
    "SupportsVariableFactory",
    "SupportsVariableManager",
    "ThreadTrackerLike",
    "VariableStoreLike",
]
