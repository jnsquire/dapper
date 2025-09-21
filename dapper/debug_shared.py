"""Shared debug adapter state and utilities to break circular imports."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any
from typing import TextIO
from typing import TypedDict

# Maximum length of strings to be sent over the wire
MAX_STRING_LENGTH = 1000

# Size of variable reference tuples (name, value)
VAR_REF_TUPLE_SIZE = 2

# Threshold for considering a string 'raw' (long/multiline)
STRING_RAW_THRESHOLD = 80

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)


class SourceReferenceMetaBase(TypedDict):
    """Required fields for a sourceReference entry."""

    path: str


class SourceReferenceMeta(SourceReferenceMetaBase, total=False):
    """Optional fields for a sourceReference entry.

    Values of SessionState.source_references map to this shape.
    - path: required absolute or relative file system path
    - name: optional display name for the source
    """

    name: str | None


class SessionState:
    """
    Singleton holder for adapter state and helper methods.
    Provides session-scoped management for sourceReferences via helper methods.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Avoid reinitializing on subsequent __new__ returns
        if getattr(self, "_initialized", False):
            return

        self.debugger: Any | None = None
        self.stop_at_entry: bool = False
        self.no_debug: bool = False
        self.command_queue: list[Any] = []
        self.command_lock = threading.Lock()
        self.is_terminated: bool = False
        self.ipc_enabled: bool = False
        self.ipc_sock: Any | None = None
        self.ipc_rfile: TextIO | None = None
        self.ipc_wfile: TextIO | None = None
        self.handle_debug_command: Any | None = None  # Set by debug_adapter_comm

        # Mapping of sourceReference -> metadata (path/name)
        self.source_references: dict[int, SourceReferenceMeta] = {}
        # Reverse mapping path -> ref id
        self._path_to_ref: dict[str, int] = {}
        # Session counter for allocating new ids
        self.next_source_ref = 1

        self._initialized = True

    # Source reference helpers
    def get_ref_for_path(self, path: str) -> int | None:
        return self._path_to_ref.get(path)

    def get_or_create_source_ref(self, path: str, name: str | None = None) -> int:
        existing = self.get_ref_for_path(path)
        if existing:
            return existing
        ref = self.next_source_ref
        try:
            self.source_references[ref] = {"path": path, "name": name}
        except Exception:
            self.source_references[ref] = {"path": path}
        self._path_to_ref[path] = ref
        self.next_source_ref = ref + 1
        return ref

    def get_source_meta(self, ref: int) -> SourceReferenceMeta | None:
        return self.source_references.get(ref)

    def get_source_content_by_ref(self, ref: int) -> str | None:
        meta = self.get_source_meta(ref)
        if not meta:
            return None
        path = meta.get("path")
        if not path:
            return None
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    def get_source_content_by_path(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


# Module-level singleton instance used throughout the codebase
state = SessionState()


def send_debug_message(event_type: str, **kwargs) -> None:
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled and state.ipc_wfile is not None:
        try:
            state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
            state.ipc_wfile.flush()
        except Exception:
            pass
        else:
            return
    send_logger.debug(json.dumps(message))
    with contextlib.suppress(Exception):
        sys.stdout.flush()


# Module-level helpers extracted from make_variable_object to reduce function size
def _format_value_str(v: Any, max_string_length: int) -> str:
    try:
        s = repr(v)
    except Exception:
        return "<Error getting value>"
    else:
        if len(s) > max_string_length:
            return s[:max_string_length] + "..."
        return s


def _allocate_var_ref(v: Any, debugger: Any | None) -> int:
    if debugger is None:
        return 0
    if not (hasattr(v, "__dict__") or isinstance(v, (dict, list, tuple))):
        return 0
    try:
        ref = debugger.next_var_ref
        debugger.next_var_ref = ref + 1
        debugger.var_refs[ref] = ("object", v)
    except Exception:
        return 0
    else:
        return ref


def _detect_kind_and_attrs(v: Any) -> tuple[str, list[str]]:
    attrs: list[str] = []
    if callable(v):
        attrs.append("hasSideEffects")
        return "method", attrs
    if isinstance(v, type):
        return "class", attrs
    if isinstance(v, (list, tuple, dict, set)):
        return "data", attrs
    if isinstance(v, (str, bytes)):
        sval = v.decode() if isinstance(v, bytes) else v
        if isinstance(sval, str) and ("\n" in sval or len(sval) > STRING_RAW_THRESHOLD):
            attrs.append("rawString")
        return "data", attrs
    return "data", attrs


def _visibility(n: Any) -> str:
    try:
        return "private" if str(n).startswith("_") else "public"
    except Exception:
        return "public"


def _detect_has_data_breakpoint(n: Any, debugger: Any | None, fr: Any | None) -> bool:
    """Best-effort detection across different debugger bookkeeping shapes.

    This intentionally avoids repeated getattr calls and keeps exception
    handling outside tight loops for performance.
    """
    if debugger is None:
        return False
    name_str = str(n)
    found = False

    # DebuggerBDB style: data_watch_names (set/list) and data_watch_meta (dict)
    dw_names = getattr(debugger, "data_watch_names", None)
    if isinstance(dw_names, (set, list)) and name_str in dw_names:
        return True
    dw_meta = getattr(debugger, "data_watch_meta", None)
    if isinstance(dw_meta, dict) and name_str in dw_meta:
        return True

    # PyDebugger/server style: _data_watches dict with dataId-like keys
    data_watches = getattr(debugger, "_data_watches", None)
    if isinstance(data_watches, dict):
        for k in list(data_watches.keys()):
            if isinstance(k, str) and (f":var:{name_str}" in k or name_str in k):
                return True

    # Frame-based mapping: _frame_watches (only check when frame supplied)
    frame_watches = getattr(debugger, "_frame_watches", None)
    if fr is not None and isinstance(frame_watches, dict):
        for data_ids in frame_watches.values():
            for did in data_ids:
                if isinstance(did, str) and (f":var:{name_str}" in did or name_str in did):
                    return True

    return found


def make_variable_object(
    name: Any, value: Any, dbg: Any | None = None, frame: Any | None = None, *, max_string_length: int = MAX_STRING_LENGTH
) -> dict[str, Any]:
    """Create a Variable-shaped dict with presentationHint and optional var-ref allocation.

    If `dbg` is provided and the value is a structured object (has __dict__ or is a dict/list/tuple),
    this function will allocate a variablesReference on the debugger object using the
    `next_var_ref` and `var_refs` attributes when available.
    """
    # Use module-level helpers for formatting/allocation/detection

    # Build the variable object using helpers
    val_str = _format_value_str(value, max_string_length)
    var_ref = _allocate_var_ref(value, dbg)
    type_name = type(value).__name__
    kind, attrs = _detect_kind_and_attrs(value)
    if _detect_has_data_breakpoint(name, dbg, frame) and "hasDataBreakpoint" not in attrs:
        attrs.append("hasDataBreakpoint")
    presentation = {"kind": kind, "attributes": attrs, "visibility": _visibility(name)}

    return {
        "name": str(name),
        "value": val_str,
        "type": type_name,
        "variablesReference": var_ref,
        "presentationHint": presentation,
    }
