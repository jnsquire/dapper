from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from dapper import debug_shared

if TYPE_CHECKING:
    from dapper.debugger_protocol import Variable


class _BreaksCollection:
    """A small container that behaves like both a list of (file,line,meta)
    and a dict mapping filename -> list[(line, meta)]. Tests in the repo use
    both styles, so this adapter keeps compatibility.
    """

    def __init__(self) -> None:
        self._by_file: dict[str, list[tuple[int, Any]]] = {}

    def add(self, filename: str, lineno: int, meta: Any | None = None) -> None:
        arr = self._by_file.get(filename)
        if arr is None:
            self._by_file[filename] = [(int(lineno), meta)]
        else:
            arr.append((int(lineno), meta))

    # list-like behaviors
    def __iter__(self):
        for fn, arr in self._by_file.items():
            for ln, meta in arr:
                yield (fn, ln, meta)

    def __contains__(self, item: object) -> bool:
        # allow checks like ("file.py", 10, None) in breaks
        if not isinstance(item, tuple) or len(item) != 3:
            return False
        fn, ln, meta = item
        arr = self._by_file.get(fn)
        if not arr:
            return False
        return any(ln == e[0] and meta == e[1] for e in arr)

    # dict-like access by filename
    def __getitem__(self, filename: str) -> list[tuple[int, Any | None]]:
        return list(self._by_file.get(filename, []))

    def pop(self, filename: str, default: list[tuple[int, Any]] | None = None):
        return self._by_file.pop(filename, default)

    def get(self, filename: str, default: list[tuple[int, Any]] | None = None):
        return self._by_file.get(filename, default)

    def items(self):
        return self._by_file.items()

    def clear(self):
        self._by_file.clear()


class DummyDebugger:
    """Unified dummy debugger used by tests.

    This class combines the behaviors seen across several test-local
    DummyDebugger copies in the codebase. It intentionally keeps a thin
    surface: bookkeeping for breaks, frames/vars, and a small set of
    control methods consumed by handlers.
    """

    def __init__(self) -> None:
        # variable/reference bookkeeping
        self.next_var_ref: int = 1
        self.var_refs: dict[int, Any] = {}
        self.frame_id_to_frame: dict[int, Any] = {}

        # thread/frame mappings
        self.frames_by_thread: dict[int, list[Any]] = {}
        self.threads: dict[int, Any] = {}
        self.current_exception_info: dict[Any, Any] = {}
        self.current_frame: Any | None = None
        self.stepping: bool = False

        # optional data breakpoint storage
        self.data_breakpoints: list[dict[str, Any]] | None = []
        # data-watch bookkeeping (kept present for typing compatibility)
        self.data_watch_names: set[str] | list[str] | None = []
        self.data_watch_meta: dict[str, Any] | None = {}
        self._data_watches: dict[str, Any] | None = None
        self._frame_watches: dict[int, list[str]] | None = None
        # launcher/debugger flags
        self.stop_on_entry: bool = False

        # breakpoint bookkeeping
        self.breakpoint_meta: dict[tuple[str, int], dict[str, Any]] = {}
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict[str, Any]] = {}

        # exception flags
        self.exception_breakpoints_raised: bool = False
        self.exception_breakpoints_uncaught: bool = False

        # misc
        self.cleared: list[Any] = []
        self.recorded: list[tuple[str, int, dict[str, Any]]] = []
        self.stopped_thread_ids: set[int] = set()

        # provide breaks as a compat container used by tests
        self.breaks = _BreaksCollection()
        # some tests expect a program_path attribute
        self.program_path: Any | None = None

        # compatibility flags used by some tests
        self._continued: bool = False
        self._next: Any | None = None
        self._step: bool = False
        self._return: Any | None = None

    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None:
        _ = temporary, funcname
        self.breaks.add(filename, int(lineno), cond)
        return None

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: Any | None = None,
        hit_condition: Any | None = None,
        log_message: Any | None = None,
    ) -> None:
        meta = {"condition": condition, "hit_condition": hit_condition, "log_message": log_message}
        # keep both a meta map and the breaks collection for compatibility
        self.breakpoint_meta[(path, int(line))] = meta
        self.recorded.append((path, int(line), meta))
        self.breaks.add(path, int(line), meta)

    def clear_breaks_for_file(self, path: str) -> None:
        self.cleared.append(path)
        self.breaks.pop(path, None)
        # remove meta entries
        to_del = [k for k in list(self.breakpoint_meta.keys()) if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def clear_break(self, filename: str, lineno: int) -> Any | None:
        # remove a specific breakpoint if present
        arr = self.breaks.get(filename)
        if arr:
            # reconstruct file entries without the lineno
            self.breaks._by_file[filename] = [b for b in arr if b[0] != int(lineno)]
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        to_del = [k for k in list(self.breakpoint_meta.keys()) if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def clear_all_function_breakpoints(self) -> None:
        self.function_breakpoints = []
        self.function_breakpoint_meta.clear()

    def set_continue(self) -> None:
        # Historic tests expect an attribute to be set when continue is
        # requested.
        self._continued = True

    def set_next(self, frame: Any) -> None:
        self._next = frame

    def set_step(self) -> None:
        self._step = True
        self.stepping = True

    def set_return(self, frame: Any) -> None:
        self._return = frame

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> Any:
        _ = cmd, args, kwargs
        return None

    def make_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Use the internal implementation to avoid recursion: calling the
        # public debug_shared.make_variable_object would call back into
        # this method. _make_variable_object_impl is the safe internal
        # builder that accepts a debugger object for var-ref allocation.
        return debug_shared._make_variable_object_impl(
            name, value, self, frame, max_string_length=max_string_length
        )

    def create_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Backwards-compatible alias used by some callers/tests
        return self.make_variable_object(name, value, frame, max_string_length=max_string_length)
