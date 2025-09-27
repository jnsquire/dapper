"""Shared debug adapter state and utilities to break circular imports."""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict

from dapper.events import EventEmitter
from dapper.ipc_binary import pack_frame  # lightweight util

if TYPE_CHECKING:
    import io
    from typing import Protocol

    from dapper.debugger_protocol import DebuggerLike

    class CommandProvider(Protocol):
        def can_handle(self, command: str) -> bool: ...

        def supported_commands(self) -> Any: ...

        def handle(self, session: SessionState, command: str, arguments: dict[str, Any], full_command: dict[str, Any]) -> dict | None: ...

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

        # Debugger instance: use structural protocol so tests can provide
        # simple dummy implementations that satisfy the expected surface.
        self.debugger: DebuggerLike | None = None
        self.stop_at_entry: bool = False
        self.no_debug: bool = False
        # Use a thread-safe FIFO queue for commands
        self.command_queue: queue.Queue[Any] = queue.Queue()
        self.is_terminated: bool = False
        self.ipc_enabled: bool = False
        self.ipc_sock: Any | None = None
        self.ipc_rfile: io.TextIOBase | None = None
        self.ipc_wfile: io.TextIOBase | None = None
        # Optional direct pipe connection object for binary send/recv on Windows
        self.ipc_pipe_conn: Any | None = None

        # Event emitter for outgoing debug messages. Consumers can subscribe
        # instead of monkeypatching the send_debug_message function.
        self.on_debug_message = EventEmitter()

        # Command dispatch provider registry
        self._providers: list[tuple[int, CommandProvider]] = []  # list of (priority, provider)
        self._providers_lock = threading.RLock()

        # Mapping of sourceReference -> metadata (path/name)
        self.source_references: dict[int, SourceReferenceMeta] = {}
        # Reverse mapping path -> ref id
        self._path_to_ref: dict[str, int] = {}
        # Session counter for allocating new ids
        self.next_source_ref = 1

        self._initialized = True

    # ------------------------------------------------------------------
    # Command provider registration and dispatch
    # ------------------------------------------------------------------
    def register_command_provider(self, provider: CommandProvider, *, priority: int = 0) -> None:
        """Register a provider that can handle debug commands.

        Providers are consulted in descending priority order. The provider
        must implement:
          - can_handle(command: str) -> bool
          - handle(session, command: str, arguments: dict[str, Any], full_command: dict[str, Any]) -> dict | None
        Returning a dict with a "success" key asks SessionState to send a
        response using the incoming command's id (if present). Returning None
        implies the provider has sent any events/responses itself.
        """
        with self._providers_lock:
            self._providers.append((int(priority), provider))
            # Highest priority first
            self._providers.sort(key=lambda p: p[0], reverse=True)

    def unregister_command_provider(self, provider: CommandProvider) -> None:
        with self._providers_lock:
            self._providers = [(pri, p) for (pri, p) in self._providers if p is not provider]

    def dispatch_debug_command(self, command: dict[str, Any]) -> None:
        """Dispatch a debug command to the first capable registered provider.

        This is the new session-aware entrypoint. It's also assigned to
        handle_debug_command for back-compat.
        """
        name = str(command.get("command", "")) if isinstance(command, dict) else ""
        arguments = command.get("arguments", {}) if isinstance(command, dict) else {}
        arguments = arguments or {}

        providers = self._providers_snapshot()
        for provider in providers:
            if not provider.can_handle(name):
                continue
            try:
                result = provider.handle(self, name, arguments, command)
            except Exception as exc:  # pragma: no cover - defensive
                self._send_error_for_exception(command, name, exc)
                return
            self._send_response_for_result(command, result)
            return

        self._send_unknown_command(command, name)

    # ---- helpers to reduce complexity
    def _providers_snapshot(self) -> list[CommandProvider]:
        with self._providers_lock:
            return [p for _, p in list(self._providers)]


    @staticmethod
    def _send_response_for_result(command: dict[str, Any], result: Any) -> None:
        if not (isinstance(result, dict) and ("success" in result)):
            return
        cmd_id = command.get("id") if isinstance(command, dict) else None
        if cmd_id is None:
            return
        response = {"id": cmd_id}
        response.update(result)
        send_debug_message("response", **response)

    @staticmethod
    def _send_error_for_exception(command: dict[str, Any], name: str, exc: Exception) -> None:
        cmd_id = command.get("id") if isinstance(command, dict) else None
        msg = f"Error handling command {name}: {exc!s}"
        if cmd_id is not None:
            send_debug_message("response", id=cmd_id, success=False, message=msg)
        else:
            send_debug_message("error", message=msg)

    @staticmethod
    def _send_unknown_command(command: dict[str, Any], name: str) -> None:
        cmd_id = command.get("id") if isinstance(command, dict) else None
        msg = f"Unknown command: {name}"
        if cmd_id is not None:
            send_debug_message("response", id=cmd_id, success=False, message=msg)
        else:
            send_debug_message("error", message=msg)

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
    """Send a debug message via IPC/logging and emit to subscribers.

    Back-compat: this function remains available; new code can subscribe to
    `state.on_debug_message` to observe messages without monkeypatching.
    """
    message = {"event": event_type}
    message.update(kwargs)

    # Emit to listeners first; listeners should never raise.
    with contextlib.suppress(Exception):
        state.on_debug_message.emit(event_type, **kwargs)

    # Prefer IPC when enabled; fall back to logging/flush.
    if state.ipc_enabled:
        # Binary IPC path
        if getattr(state, "ipc_binary", False):
            payload = json.dumps(message).encode("utf-8")
            frame = pack_frame(1, payload)
            # Prefer pipe conn if available
            conn = state.ipc_pipe_conn
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.send_bytes(frame)
                    return
            # Else try binary file
            wfile = state.ipc_wfile
            if wfile is not None:
                with contextlib.suppress(Exception):
                    # Assume binary BufferedWriter
                    wfile.write(frame)  # type: ignore[arg-type]
                    with contextlib.suppress(Exception):
                        wfile.flush()  # type: ignore[call-arg]
                    return
        # Text IPC path
        if state.ipc_wfile is not None:
            try:
                state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
                state.ipc_wfile.flush()
            except Exception:
                pass
            else:
                return
    send_logger.debug(json.dumps(message))
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


def _allocate_var_ref(v: Any, debugger: DebuggerLike | None) -> int:
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


def _detect_has_data_breakpoint(n: Any, debugger: DebuggerLike | None, fr: Any | None) -> bool:
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
    name: Any,
    value: Any,
    dbg: DebuggerLike | None = None,
    frame: Any | None = None,
    *,
    max_string_length: int = MAX_STRING_LENGTH,
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
