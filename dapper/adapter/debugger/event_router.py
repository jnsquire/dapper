from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING
from typing import Any

from dapper.adapter.payload_extractor import extract_payload
from dapper.adapter.types import PyDebuggerThread

if TYPE_CHECKING:
    from dapper.adapter.debugger.py_debugger import PyDebugger

logger = logging.getLogger(__name__)


class _PyDebuggerEventRouter:
    """Routes and applies debuggee events for a ``PyDebugger`` instance."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    def handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle stopped event state updates."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "breakpoint")

        with self._debugger.lock:
            thread = self._debugger.get_thread(thread_id)
            if thread is None:
                thread = PyDebuggerThread(thread_id, f"Thread {thread_id}")
                self._debugger.set_thread(thread_id, thread)
            thread.is_stopped = True
            thread.stop_reason = reason

        try:
            self._debugger.stopped_event.set()
        except Exception:
            try:
                self._debugger.loop.call_soon_threadsafe(self._debugger.stopped_event.set)
            except Exception:
                with contextlib.suppress(Exception):
                    self._debugger.stopped_event.set()

    def handle_event_thread(self, data: dict[str, Any]) -> None:
        """Handle thread started/exited state updates."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "started")

        if reason == "started":
            with self._debugger.lock:
                if self._debugger.get_thread(thread_id) is None:
                    default_name = f"Thread {thread_id}"
                    thread_name = data.get("name", default_name)
                    self._debugger.set_thread(thread_id, PyDebuggerThread(thread_id, thread_name))
        else:
            with self._debugger.lock:
                self._debugger.remove_thread(thread_id)

    def handle_event_exited(self, data: dict[str, Any]) -> None:
        """Handle debuggee exited event and schedule cleanup."""
        exit_code = data.get("exitCode", 0)
        self._debugger.is_terminated = True
        self._debugger.schedule_program_exit(exit_code)

    def handle_event_stacktrace(self, data: dict[str, Any]) -> None:
        """Cache stack trace data from the debuggee."""
        thread_id = data.get("threadId", 1)
        stack_frames = data.get("stackFrames", [])
        with self._debugger.lock:
            self._debugger.cache_stack_frames(thread_id, stack_frames)

    def handle_event_variables(self, data: dict[str, Any]) -> None:
        """Cache variables payload from the debuggee."""
        var_ref = data.get("variablesReference", 0)
        variables = data.get("variables", [])
        with self._debugger.lock:
            self._debugger.cache_var_ref(var_ref, variables)

    def handle_debug_message(self, message: str) -> None:
        """Handle a debug protocol message from the debuggee."""
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        command_id = data.get("id")
        if command_id is not None and self._debugger.has_pending_command(command_id):
            future = self._debugger.pop_pending_command(command_id)
            if future is not None:
                self._debugger.resolve_pending_response(future, data)
            return

        event_type: str | None = data.get("event")
        if event_type is None:
            return

        if event_type == "stopped":
            self.handle_event_stopped(data)
        elif event_type == "thread":
            self.handle_event_thread(data)
        elif event_type == "exited":
            self.handle_event_exited(data)
            return
        elif event_type == "stackTrace":
            self.handle_event_stacktrace(data)
            return
        elif event_type == "variables":
            self.handle_event_variables(data)
            return

        payload = extract_payload(event_type, data)
        if payload is not None:
            self._debugger.emit_event(event_type, payload)
