"""Typing protocol for debugger objects used by handlers and launcher.

This defines the minimal surface used by our command handlers and launcher
so that tests can provide simple dummy implementations without inheriting
from the real DebuggerBDB.
"""

from __future__ import annotations

from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Literal
from typing import Protocol
from typing import TypedDict
from typing import Union
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


@runtime_checkable
class DebuggerLike(Protocol):
    # Common attributes consumed by handlers/launcher/tests
    next_var_ref: int
    # Variable reference bookkeeping can store several shapes:
    # - ("object", value) for allocated object references
    # - (frame_id, "locals"|"globals") for scope-backed refs
    # - a list of variable-shaped dicts used when server caches variables
    VarRefObject = tuple[Literal["object"], Any]
    VarRefScope = tuple[int, Literal["locals", "globals"]]
    VarRefList = list[Variable]
    VarRef = Union[VarRefObject, VarRefScope, VarRefList]

    var_refs: dict[int, VarRef]
    frame_id_to_frame: dict[int, Any]
    frames_by_thread: dict[int, list]
    threads: dict[int, Any]
    # Map thread id (int) -> exception info payload. Use the structured
    # `ExceptionInfo` TypedDict to provide better static guarantees to
    # callers and IDEs.
    current_exception_info: dict[int, ExceptionInfo]
    # Current frame for stepping APIs
    current_frame: Any | None
    # Whether currently stepping
    stepping: bool

    # Optional in practice; launcher writes to it when present
    data_breakpoints: list[dict[str, Any]] | None
    # Optional flag on some debugger implementations used by launcher
    stop_on_entry: bool
    # Optional data-watch bookkeeping helpers used by _detect_has_data_breakpoint
    # - data_watch_names: set or list of watched variable names
    # - data_watch_meta: mapping of name -> metadata
    # - _data_watches: dict of data-id-like keys (string) -> metadata
    # - _frame_watches: mapping of frame_id -> list of dataId strings
    # data_watch_names can be a set or list of watched variable names
    data_watch_names: set[str] | list[str] | None
    # metadata mapping for watched names (adapter may store lists of metas)
    data_watch_meta: dict[str, Any] | None
    # server-side mapping of dataId-like keys -> metadata
    _data_watches: dict[str, Any] | None
    # optional mapping of frame_id -> list[dataId strings]
    _frame_watches: dict[int, list[str]] | None

    # Breakpoint APIs used by dap_command_handlers (match bdb.Bdb signatures)
    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None: ...

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: Any | None,
        hit_condition: Any | None,
        log_message: Any | None,
    ) -> None: ...

    # Clear helpers: implementations may provide either of these; handlers
    # will fall back appropriately.
    def clear_breaks_for_file(self, path: str) -> None: ...
    def clear_break(self, filename: str, lineno: int) -> Any | None: ...

    # Extended breakpoint and exception controls used in handlers/launcher
    def clear_break_meta_for_file(self, path: str) -> None: ...
    def clear_all_function_breakpoints(self) -> None: ...

    # Function breakpoint bookkeeping
    function_breakpoints: list[str]
    function_breakpoint_meta: dict[str, dict[str, Any]]

    # Exception breakpoint flags
    exception_breakpoints_raised: bool
    exception_breakpoints_uncaught: bool

    # Thread stop/continue and stepping controls
    stopped_thread_ids: Any

    def set_continue(self) -> None: ...
    def set_next(self, frame: Any) -> None: ...
    def set_step(self) -> None: ...
    def set_return(self, frame: Any) -> None: ...

    # Code execution entry used by launcher
    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> Any: ...

    # Frame evaluation integration
    breakpoints: dict[str, list[Any]]

    # PyDebugger interface
    def set_breakpoints(
        self, source: str, breakpoints: list[dict[str, Any]], **kwargs: Any
    ) -> None: ...

    # Optional methods for frame evaluation
    def user_line(self, frame: Any) -> Any | None: ...
    def set_trace(self, frame: Any = None) -> None: ...

    # Optional attributes for frame evaluation
    custom_breakpoints: ClassVar[dict[str, Any]]

    # Private attributes used by the integration (optional)
    _frame_eval_enabled: bool
    _mock_user_line: Any  # Used for testing

    # Trace function management
    def get_trace_function(self) -> Callable[[Any | None, str | None, Any | None], Any | None]:
        """Get the current trace function.

        Returns:
            The current trace function that takes (frame, event, arg) as arguments.
        """
        ...

    def set_trace_function(
        self, trace_func: Callable[[Any | None, str | None, Any | None], Any | None] | None
    ) -> None:
        """Set a new trace function.

        Args:
            trace_func: The new trace function that takes (frame, event, arg) as arguments.
                       If None, clears the current trace function.
        """
        ...

    # Create a Variable-shaped dict for value presentation and var-ref allocation
    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,
        *,
        max_string_length: int = 1000,
    ) -> Variable: ...


__all__ = ["DebuggerLike"]
