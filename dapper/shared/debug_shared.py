"""Shared debug adapter state and utilities to break circular imports."""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import json
import logging
import os
from pathlib import Path
import queue
import re
import sys
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import TypedDict
from typing import cast
from urllib.parse import urlparse
from urllib.request import url2pathname

from dapper.ipc.ipc_binary import pack_frame  # lightweight util
from dapper.shared.runtime_source_registry import RuntimeSourceEntry
from dapper.shared.runtime_source_registry import RuntimeSourceRegistry
from dapper.utils.events import EventEmitter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.debugger_protocol import Variable

    class CommandProvider(Protocol):
        def can_handle(self, command: str) -> bool: ...

        def handle(
            self,
            session: DebugSession,
            command: str,
            arguments: dict[str, Any],
            full_command: dict[str, Any],
        ) -> dict[str, Any] | None: ...


# Maximum length of strings to be sent over the wire
MAX_STRING_LENGTH = 1000

# Size of variable reference tuples (name, value)
VAR_REF_TUPLE_SIZE = 2

# Threshold for considering a string 'raw' (long/multiline)
STRING_RAW_THRESHOLD = 80

# Number of positional args for the simple make_variable_object signature
MAKE_VAR_SIMPLE_ARGCOUNT = 2

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)


class SourceReferenceMetaBase(TypedDict):
    """Required fields for a sourceReference entry."""

    path: str


class SourceReferenceMeta(SourceReferenceMetaBase, total=False):
    """Optional fields for a sourceReference entry.

    Values of DebugSession.source_references map to this shape.
    - path: required absolute or relative file system path
    - name: optional display name for the source
    """

    name: str | None


def _default_exit_func() -> Callable[[int], Any]:
    """Return the process-exit function appropriate for the environment."""

    def _test_exit(code: int) -> None:  # pragma: no cover - test-time behavior
        raise SystemExit(code)

    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return _test_exit
    return os._exit


class SessionTransport:
    """IPC transport state + outbound send behavior for a debug session."""

    def __init__(self) -> None:
        self.ipc_enabled: bool = False
        self.ipc_binary: bool = False
        self.ipc_sock: Any | None = None
        self.ipc_rfile: Any | None = None
        self.ipc_wfile: Any | None = None
        self.ipc_pipe_conn: Any | None = None
        self.on_debug_message = EventEmitter()
        # The request id of the command currently being handled.  Set by
        # ``request_scope()`` and cleared on exit.  Handlers read this via
        # ``_current_request_id()`` to attach the id explicitly when
        # constructing response messages.
        self.current_request_id: int | str | None = None
        # Tracks whether a response has already been sent for the current
        # command dispatch cycle.  Set automatically by ``send()`` when a
        # response is emitted; checked by the dispatcher to decide whether to
        # send a default acknowledgement.
        self.response_sent: bool = False

    @contextlib.contextmanager
    def request_scope(self, request_id: int | str | None) -> Iterator[SessionTransport]:
        """Context manager that brackets a single request lifecycle.

        Sets ``current_request_id`` on entry (readable by handlers via
        ``_current_request_id()``) and clears it on exit.  Also resets
        ``response_sent`` so the dispatcher can detect whether a handler
        already sent its own response.
        """
        self.current_request_id = request_id
        self.response_sent = False

        try:
            yield self
        finally:
            self.current_request_id = None
            self.response_sent = False

    def require_ipc(self) -> None:
        if not self.ipc_enabled:
            msg = "IPC is required but not enabled"
            raise RuntimeError(msg)

    def require_ipc_write_channel(self) -> None:
        if self.ipc_pipe_conn is None and self.ipc_wfile is None:
            msg = "IPC enabled but no connection available"
            raise RuntimeError(msg)

    def send(self, message_type: str, **kwargs: Any) -> None:
        """Send a debug message via IPC and emit to subscribers."""
        message: dict[str, Any] = {"event": message_type}
        message.update(kwargs)

        # Track that a response has been sent for the current request
        # lifecycle so the dispatcher knows not to send a default ack.
        if message_type == "response":
            self.response_sent = True
            if "id" not in message or message["id"] is None:
                logger.warning(
                    "Sending response without id (current_request_id=%s, keys=%s)",
                    self.current_request_id,
                    list(message.keys()),
                )

        with contextlib.suppress(Exception):
            self.on_debug_message.emit(message_type, **kwargs)

        self.require_ipc()
        self.require_ipc_write_channel()

        payload = json.dumps(message).encode("utf-8")
        frame = pack_frame(1, payload)

        conn = self.ipc_pipe_conn
        if conn is not None:
            conn.send_bytes(frame)
            return

        wfile = self.ipc_wfile
        assert wfile is not None  # guaranteed by require_ipc_write_channel
        wfile.write(frame)
        with contextlib.suppress(Exception):
            wfile.flush()


class SourceCatalog:
    """Session-scoped sourceReference registry and file-content resolution."""

    def __init__(self) -> None:
        self.source_references: dict[int, SourceReferenceMeta] = {}
        self._path_to_ref: dict[str, int] = {}
        self.next_source_ref = itertools.count(1)
        self._source_provider_lock = threading.RLock()
        self._source_providers: list[tuple[int, Callable[[str], str | None]]] = []
        self._next_source_provider_id = itertools.count(1)
        # Registry for in-memory / synthetic sources (eval, exec, Jinja, etc.)
        self._dynamic = RuntimeSourceRegistry()

    def get_ref_for_path(self, path: str) -> int | None:
        return self._path_to_ref.get(path)

    def get_path_to_ref_map(self) -> dict[str, int]:
        return self._path_to_ref

    def set_path_to_ref_map(self, value: dict[str, int]) -> None:
        self._path_to_ref = value

    def get_or_create_source_ref(self, path: str, name: str | None = None) -> int:
        existing = self.get_ref_for_path(path)
        if existing:
            return existing
        ref = next(self.next_source_ref)
        try:
            self.source_references[ref] = {"path": path, "name": name}
        except Exception:
            self.source_references[ref] = {"path": path}
        self._path_to_ref[path] = ref
        return ref

    def get_source_meta(self, ref: int) -> SourceReferenceMeta | None:
        return self.source_references.get(ref)

    def register_dynamic_source(
        self,
        virtual_path: str,
        source_text: str,
        *,
        name: str | None = None,
        origin: str = "dynamic",
    ) -> int:
        """Register an in-memory source string for a non-filesystem code object.

        Allocates a ``sourceReference`` integer (reusing any existing one for
        *virtual_path*) and stores both the metadata in
        :attr:`source_references` and the source text in the dynamic
        :class:`~dapper.shared.runtime_source_registry.RuntimeSourceRegistry`.

        Args:
            virtual_path: Synthetic filename (e.g. ``"<string>"``).  Used as
                          the path key for later ``source`` request look-ups.
            source_text:  Complete source content to serve to DAP clients.
            name:         Human-readable display name (falls back to *virtual_path*).
            origin:       Provenance tag, e.g. ``"eval"`` or ``"jinja"``.

        Returns:
            The integer ``sourceReference`` for this entry.
        """
        ref = self.get_or_create_source_ref(virtual_path, name=name)
        self._dynamic.register(virtual_path, source_text, name=name, origin=origin, ref_hint=ref)
        return ref

    def get_dynamic_sources(self) -> list[RuntimeSourceEntry]:
        """Return all registered dynamic (in-memory) source entries."""
        return self._dynamic.all_entries()

    def get_or_register_dynamic_from_linecache(
        self,
        path: str,
    ) -> int:
        """Look up *path* in :mod:`linecache`, register the content, and return the ref.

        If ``linecache`` has no content for *path* a placeholder comment is
        registered instead so that a valid ``sourceReference`` is still
        returned.  Idempotent — calling with the same *path* twice returns the
        same ref.

        Args:
            path: Synthetic filename, e.g. ``"<string>"``.

        Returns:
            The integer ``sourceReference`` allocated for *path*.
        """
        entry = self._dynamic.get_or_register_from_linecache(path)
        if entry is not None:
            return self.register_dynamic_source(
                path, entry.source_text, name=entry.name, origin=entry.origin
            )
        placeholder = f"# source not available for {path}\n"
        return self.register_dynamic_source(path, placeholder, origin="placeholder")

    def get_source_content_by_ref(self, ref: int) -> str | None:
        # Check the dynamic (in-memory) store before attempting a disk read.
        text = self._dynamic.get_source_text(ref)
        if text is not None:
            return text
        meta = self.get_source_meta(ref)
        if not meta:
            return None
        path = meta.get("path")
        if not path:
            return None
        return self.get_source_content_by_path(path)

    def register_source_provider(self, provider: Callable[[str], str | None]) -> int:
        provider_id = next(self._next_source_provider_id)
        with self._source_provider_lock:
            self._source_providers.append((provider_id, provider))
        return provider_id

    def unregister_source_provider(self, provider_id: int) -> bool:
        with self._source_provider_lock:
            existing_len = len(self._source_providers)
            self._source_providers = [
                (pid, provider) for (pid, provider) in self._source_providers if pid != provider_id
            ]
            return len(self._source_providers) != existing_len

    @staticmethod
    def _normalize_path_or_uri(path_or_uri: str) -> tuple[str, bool]:
        # Fast-path: detect Windows drive-letter absolute paths before
        # invoking urlparse. urlparse treats strings like "C:\\path" as
        # having a single-letter scheme, so check first to avoid that.
        if re.match(r"^[A-Za-z]:[\\/].*", path_or_uri):
            return path_or_uri, True

        parsed = urlparse(path_or_uri)

        # If there's no scheme, treat as a plain filesystem path.
        if not parsed.scheme:
            return path_or_uri, True

        # Only accept file:// URIs for disk access; other schemes are
        # considered non-filesystem and should not be attempted on disk.
        if parsed.scheme.lower() != "file":
            return path_or_uri, False

        normalized_path = url2pathname(parsed.path)
        if parsed.netloc:
            if parsed.netloc.lower() == "localhost":
                return normalized_path, True
            return path_or_uri, False
        return normalized_path, True

    def get_source_content_by_path(self, path_or_uri: str) -> str | None:
        # Check the dynamic (in-memory) store first — handles synthetic
        # filenames like "<string>" that can never exist on disk.
        text = self._dynamic.get_source_text_by_path(path_or_uri)
        if text is not None:
            return text

        with self._source_provider_lock:
            providers = list(self._source_providers)

        for provider_id, provider in providers:
            try:
                resolved = provider(path_or_uri)
            except Exception:
                logger.debug(
                    "source provider %s failed for %s",
                    provider_id,
                    path_or_uri,
                    exc_info=True,
                )
                continue
            if isinstance(resolved, str):
                logger.debug(
                    "source provider %s returned content for %s", provider_id, path_or_uri
                )
                return resolved
            logger.debug("source provider %s returned no content for %s", provider_id, path_or_uri)

        normalized_path, should_try_disk = self._normalize_path_or_uri(path_or_uri)
        if not should_try_disk:
            return None

        try:
            return Path(normalized_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


class ProcessControl:
    """Process lifecycle hooks used by terminate/restart flows."""

    def __init__(self) -> None:
        self.exit_func: Callable[[int], Any] = _default_exit_func()
        self.exec_func: Callable[[str, list[str]], Any] = os.execv


class CommandDispatcher:
    """Provider-based command dispatch with session-aware error responses."""

    def __init__(self) -> None:
        self._providers: list[tuple[int, CommandProvider]] = []
        self._providers_lock = threading.RLock()

    def register_command_provider(self, provider: CommandProvider, *, priority: int = 0) -> None:
        with self._providers_lock:
            self._providers.append((int(priority), provider))
            self._providers.sort(key=lambda p: p[0], reverse=True)

    def get_providers(self) -> list[tuple[int, CommandProvider]]:
        with self._providers_lock:
            return list(self._providers)

    def set_providers(self, value: list[tuple[int, CommandProvider]]) -> None:
        with self._providers_lock:
            self._providers = list(value)

    def get_providers_lock(self) -> threading.RLock:
        return self._providers_lock

    def unregister_command_provider(self, provider: CommandProvider) -> None:
        with self._providers_lock:
            self._providers = [(pri, p) for (pri, p) in self._providers if p is not provider]

    def dispatch_debug_command(self, session: DebugSession, command: dict[str, Any]) -> None:
        name = str(command.get("command", "")) if isinstance(command, dict) else ""
        raw_arguments = command.get("arguments", {}) if isinstance(command, dict) else {}
        arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}

        with self._providers_lock:
            providers = [p for _, p in list(self._providers)]
        for provider in providers:
            if not provider.can_handle(name):
                continue

            try:
                result = provider.handle(session, name, arguments, command)
            except Exception as exc:  # pragma: no cover - defensive
                self._send_error_for_exception(command, name, exc)
                return
            self._send_response_for_result(command, result)
            return

        self._send_unknown_command(command, name)

    @staticmethod
    def _send_response_for_result(command: dict[str, Any], result: dict[str, Any] | None) -> None:
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


class DebugSession:
    """Composed debug session containing focused state/services."""

    def __init__(self) -> None:
        self._initialize_mutable_state()

    @staticmethod
    def _default_exit_func() -> Callable[[int], Any]:
        return _default_exit_func()

    def _initialize_mutable_state(self) -> None:
        self.debugger: DebuggerLike | None = None
        self.stop_at_entry: bool = False
        self.no_debug: bool = False
        self.session_id: str | None = None
        self.parent_session_id: str | None = None
        self.module_search_paths: list[str] = []
        self.command_queue: queue.Queue[Any] = queue.Queue()
        self.configuration_done_event: threading.Event = threading.Event()
        self.debugger_configured_event: threading.Event = threading.Event()
        self._resume_event: threading.Event = threading.Event()
        self.is_terminated: bool = False
        self.command_thread: threading.Thread | None = None

        self.transport = SessionTransport()
        self.sources = SourceCatalog()
        self.dispatcher = CommandDispatcher()
        self.process_control = ProcessControl()

    def signal_resume(self) -> None:
        """Signal the resume event to unblock the debugger thread."""
        logger.debug("signal_resume: unblocking debugger thread (session_id=%s)", self.session_id)
        self._resume_event.set()

    def exit_if_alive(self, code: int = 0) -> None:
        """Call ``exit_func`` only if the session has not already been terminated."""
        if not self.is_terminated:
            logger.debug(
                "exit_if_alive: exiting with code %d (session_id=%s)", code, self.session_id
            )
            self.exit_func(code)
        else:
            logger.debug(
                "exit_if_alive: already terminated, ignoring (session_id=%s)", self.session_id
            )

    def terminate_session(self) -> None:
        """Mark the session as terminated and unblock the debugger thread."""
        logger.info("terminate_session: marking terminated (session_id=%s)", self.session_id)
        self.is_terminated = True
        self.signal_resume()

    # ------------------------------------------------------------------
    # Request lifecycle helpers
    # ------------------------------------------------------------------

    @property
    def request_id(self) -> int | str | None:
        """The request id of the command currently being handled.

        Reads the value set by :meth:`SessionTransport.request_scope` on the
        transport.  Handlers use this when constructing response messages so
        the ``id`` is attached explicitly at the construction site.
        """
        return self.transport.current_request_id

    def safe_send(self, message_type: str, **payload: Any) -> bool:
        """Send a debug message, swallowing transport errors.

        Returns ``True`` on success, ``False`` if a transport-layer
        exception was caught and suppressed.
        """
        try:
            self.transport.send(message_type, **payload)
        except (BrokenPipeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug("Failed to send debug message '%s'", message_type, exc_info=True)
            return False
        else:
            return True

    def safe_send_response(self, **payload: Any) -> bool:
        """Send a DAP response for the current request, swallowing transport errors.

        Equivalent to ``safe_send("response", id=self.request_id, **payload)``
        but removes the boilerplate that every command handler repeats.

        Common usage::

            session.safe_send_response(success=True)
            session.safe_send_response(**result)
            session.safe_send_response(success=False, message="...")
        """
        return self.safe_send("response", id=self.request_id, **payload)

    @property
    def ipc_enabled(self) -> bool:
        return self.transport.ipc_enabled

    @ipc_enabled.setter
    def ipc_enabled(self, value: bool) -> None:
        self.transport.ipc_enabled = bool(value)

    @property
    def ipc_binary(self) -> bool:
        return self.transport.ipc_binary

    @ipc_binary.setter
    def ipc_binary(self, value: bool) -> None:
        self.transport.ipc_binary = bool(value)

    @property
    def ipc_sock(self) -> Any | None:
        return self.transport.ipc_sock

    @ipc_sock.setter
    def ipc_sock(self, value: Any | None) -> None:
        self.transport.ipc_sock = value

    @property
    def ipc_rfile(self) -> Any | None:
        return self.transport.ipc_rfile

    @ipc_rfile.setter
    def ipc_rfile(self, value: Any | None) -> None:
        self.transport.ipc_rfile = value

    @property
    def ipc_wfile(self) -> Any | None:
        return self.transport.ipc_wfile

    @ipc_wfile.setter
    def ipc_wfile(self, value: Any | None) -> None:
        self.transport.ipc_wfile = value

    @property
    def ipc_pipe_conn(self) -> Any | None:
        return self.transport.ipc_pipe_conn

    @ipc_pipe_conn.setter
    def ipc_pipe_conn(self, value: Any | None) -> None:
        self.transport.ipc_pipe_conn = value

    @property
    def on_debug_message(self) -> EventEmitter:
        return self.transport.on_debug_message

    @property
    def source_references(self) -> dict[int, SourceReferenceMeta]:
        return self.sources.source_references

    @source_references.setter
    def source_references(self, value: dict[int, SourceReferenceMeta]) -> None:
        self.sources.source_references = value

    @property
    def _path_to_ref(self) -> dict[str, int]:
        return self.sources.get_path_to_ref_map()

    @_path_to_ref.setter
    def _path_to_ref(self, value: dict[str, int]) -> None:
        self.sources.set_path_to_ref_map(value)

    @property
    def next_source_ref(self) -> Any:
        return self.sources.next_source_ref

    @next_source_ref.setter
    def next_source_ref(self, value: Any) -> None:
        self.sources.next_source_ref = value

    @property
    def exit_func(self) -> Callable[[int], Any]:
        return self.process_control.exit_func

    @exit_func.setter
    def exit_func(self, fn: Callable[[int], Any]) -> None:
        self.process_control.exit_func = fn

    @property
    def exec_func(self) -> Callable[[str, list[str]], Any]:
        return self.process_control.exec_func

    @exec_func.setter
    def exec_func(self, fn: Callable[[str, list[str]], Any]) -> None:
        self.process_control.exec_func = fn

    @property
    def _providers(self) -> list[tuple[int, CommandProvider]]:
        return self.dispatcher.get_providers()

    @_providers.setter
    def _providers(self, value: list[tuple[int, CommandProvider]]) -> None:
        self.dispatcher.set_providers(value)

    @property
    def _providers_lock(self) -> threading.RLock:
        return self.dispatcher.get_providers_lock()

    def get_command_providers(self) -> list[tuple[int, CommandProvider]]:
        return self.dispatcher.get_providers()

    def require_ipc(self) -> None:
        self.transport.require_ipc()

    def require_ipc_write_channel(self) -> None:
        self.transport.require_ipc_write_channel()

    def process_queued_commands_launcher(self) -> None:
        """Block until a resume command (continue/step/terminate) is processed.

        The IPC listener thread dispatches incoming commands directly via
        ``handle_debug_command``.  This method simply waits for one of those
        dispatches to signal ``_resume_event``, which happens when a resume
        command (continue, next, stepIn, stepOut, terminate) is handled.
        """
        logger.debug(
            "process_queued_commands_launcher: waiting for resume (session_id=%s)", self.session_id
        )
        self._resume_event.clear()
        while not self.is_terminated:
            if self._resume_event.wait(timeout=0.5):
                logger.debug(
                    "process_queued_commands_launcher: resume signalled (session_id=%s)",
                    self.session_id,
                )
                break
        if self.is_terminated:
            logger.debug(
                "process_queued_commands_launcher: session terminated (session_id=%s)",
                self.session_id,
            )

    def set_exit_func(self, fn: Callable[[int], Any]) -> None:
        self.exit_func = fn

    def set_exec_func(self, fn: Callable[[str, list[str]], Any]) -> None:
        self.exec_func = fn

    def start_command_receiver(self) -> None:
        """Start the debug command receiving thread.

        This is a safe, idempotent helper that defers the import to avoid
        circular-import issues. Failures are logged rather than silently
        ignored so misconfiguration is visible during startup.
        """
        try:
            # Defer import to avoid circular import at module import time
            from dapper.ipc import ipc_receiver  # noqa: PLC0415

            # Avoid starting more than once
            if self.command_thread is not None:
                logger.debug("command receiver already started")
                return

            self.command_thread = threading.Thread(
                target=ipc_receiver.receive_debug_commands,
                daemon=True,
                name="dapper-recv-cmd",
            )
            self.command_thread.start()
            logger.debug("Started receive_debug_commands thread")
        except Exception as exc:  # pragma: no cover - best-effort startup
            # Log at warning level so failures are visible during normal runs
            logger.warning(
                "Failed to start receive_debug_commands thread: %s",
                exc,
                exc_info=True,
            )

    def register_command_provider(self, provider: CommandProvider, *, priority: int = 0) -> None:
        self.dispatcher.register_command_provider(provider, priority=priority)

    def unregister_command_provider(self, provider: CommandProvider) -> None:
        self.dispatcher.unregister_command_provider(provider)

    def dispatch_debug_command(self, command: dict[str, Any]) -> None:
        self.dispatcher.dispatch_debug_command(self, command)

    # Source reference helpers
    def get_ref_for_path(self, path: str) -> int | None:
        return self.sources.get_ref_for_path(path)

    def get_or_create_source_ref(self, path: str, name: str | None = None) -> int:
        return self.sources.get_or_create_source_ref(path, name)

    def get_source_meta(self, ref: int) -> SourceReferenceMeta | None:
        return self.sources.get_source_meta(ref)

    def get_source_content_by_ref(self, ref: int) -> str | None:
        return self.sources.get_source_content_by_ref(ref)

    def get_source_content_by_path(self, path: str) -> str | None:
        return self.sources.get_source_content_by_path(path)

    def register_source_provider(self, provider: Callable[[str], str | None]) -> int:
        return self.sources.register_source_provider(provider)

    def unregister_source_provider(self, provider_id: int) -> bool:
        return self.sources.unregister_source_provider(provider_id)

    def register_dynamic_source(
        self,
        virtual_path: str,
        source_text: str,
        *,
        name: str | None = None,
        origin: str = "dynamic",
    ) -> int:
        """Register an in-memory source string for a synthetic code object.

        Convenience delegation to
        :meth:`~dapper.shared.debug_shared.SourceCatalog.register_dynamic_source`.
        Returns the integer ``sourceReference`` allocated for *virtual_path*.
        """
        return self.sources.register_dynamic_source(
            virtual_path, source_text, name=name, origin=origin
        )

    def get_dynamic_sources(self) -> list[RuntimeSourceEntry]:
        """Return all registered dynamic (in-memory) source entries."""
        return self.sources.get_dynamic_sources()


# Module-level singleton instance used throughout the codebase
state = DebugSession()

# Context-local active session for injection-friendly call paths.
_active_session: contextvars.ContextVar[DebugSession | None] = contextvars.ContextVar(
    "dapper_active_session",
    default=None,
)


def get_active_session() -> DebugSession:
    """Return the context-local active session, falling back to global state."""
    active = _active_session.get()
    return active if active is not None else state


@contextlib.contextmanager
def use_session(session: DebugSession) -> Iterator[DebugSession]:
    """Temporarily set the active session for the current context."""
    token = _active_session.set(session)
    try:
        yield session
    finally:
        _active_session.reset(token)


def send_debug_message(message_type: str, **kwargs: Any) -> None:
    """Send a debug message via the active session transport."""
    get_active_session().transport.send(message_type, **kwargs)


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
        ref = debugger.var_manager.next_var_ref
        debugger.var_manager.next_var_ref = ref + 1
        debugger.var_manager.var_refs[ref] = ("object", v)
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
    """
    Determines the visibility of a variable or attribute name.
    Returns 'private' if the name starts with an underscore, otherwise 'public'.
    """
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

    # DebuggerBDB style: data_watch_names (set/list) and data_watch_meta (dict)
    dw_names = (
        getattr(debugger.data_bp_state, "watch_names", None)
        if hasattr(debugger, "data_bp_state")
        else None
    )
    if isinstance(dw_names, (set, list)) and name_str in dw_names:
        return True
    dw_meta = (
        getattr(debugger.data_bp_state, "watch_meta", None)
        if hasattr(debugger, "data_bp_state")
        else None
    )
    if isinstance(dw_meta, dict) and name_str in dw_meta:
        return True

    # PyDebugger/server style: _data_watches dict with dataId-like keys
    data_watches = (
        getattr(debugger.data_bp_state, "data_watches", None)
        if hasattr(debugger, "data_bp_state")
        else None
    )
    if isinstance(data_watches, dict):
        for k in list(data_watches.keys()):
            if isinstance(k, str) and (f":var:{name_str}" in k or name_str in k):
                return True

    # Frame-based mapping: _frame_watches (only check when frame supplied)
    frame_watches = (
        getattr(debugger.data_bp_state, "frame_watches", None)
        if hasattr(debugger, "data_bp_state")
        else None
    )
    if fr is not None and isinstance(frame_watches, dict):
        for data_ids in frame_watches.values():
            for did in data_ids:
                if isinstance(did, str) and (f":var:{name_str}" in did or name_str in did):
                    return True

    return False


def _make_variable_object_impl(
    name: Any,
    value: Any,
    dbg: DebuggerLike | None = None,
    frame: Any | None = None,
    *,
    max_string_length: int = MAX_STRING_LENGTH,
) -> Variable:
    """Internal implementation that builds the Variable-shaped dict.

    This function uses the module-level helpers to format the value string,
    allocate variable references on the debugger (when present), and
    produce the presentationHint structure expected by clients.
    """
    val_str = _format_value_str(value, max_string_length)
    var_ref = _allocate_var_ref(value, dbg)
    type_name = type(value).__name__
    kind, attrs = _detect_kind_and_attrs(value)
    if _detect_has_data_breakpoint(name, dbg, frame) and "hasDataBreakpoint" not in attrs:
        attrs.append("hasDataBreakpoint")

    presentation = {"kind": kind, "attributes": attrs, "visibility": _visibility(name)}

    return cast(
        "Variable",
        {
            "name": str(name),
            "value": val_str,
            "type": type_name,
            "variablesReference": var_ref,
            "presentationHint": presentation,
        },
    )


def make_variable_object(
    name: Any,
    value: Any,
    dbg: DebuggerLike | None = None,
    frame: Any | None = None,
    *,
    max_string_length: int = MAX_STRING_LENGTH,
) -> Variable:
    """Build the Variable-shaped dict, preferring a debugger implementation.

    If the active debugger exposes `make_variable_object`, call it (accepting
    either a simple (name, value) signature or an extended one). If that
    fails or is absent, fall back to the internal implementation.
    """
    if dbg is not None:
        res = dbg.make_variable_object(name, value, frame, max_string_length=max_string_length)
        if isinstance(res, dict):
            return cast("Variable", res)

    return _make_variable_object_impl(name, value, dbg, frame, max_string_length=max_string_length)
