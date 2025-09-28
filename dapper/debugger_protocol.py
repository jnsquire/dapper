"""Typing protocol for debugger objects used by handlers and launcher.

This defines the minimal surface used by our command handlers and launcher
so that tests can provide simple dummy implementations without inheriting
from the real DebuggerBDB.
"""

from __future__ import annotations

from typing import Any
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
    current_exception_info: dict[str, Any]
    # Current frame for stepping APIs
    current_frame: Any | None
    # Whether currently stepping
    stepping: bool

    # Optional in practice; launcher writes to it when present
    data_breakpoints: list[dict[str, Any]] | None

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

    # Create a Variable-shaped dict for value presentation and var-ref allocation
    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,
        *,
        max_string_length: int = 1000,
    ) -> dict[str, Any]: ...

    # Historical launcher helper name; accept both to be lenient for callers/tests
    def create_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,
        *,
        max_string_length: int = 1000,
    ) -> dict[str, Any]: ...


__all__ = ["DebuggerLike"]
