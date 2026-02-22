from __future__ import annotations

# ruff: noqa: SLF001
import logging
import subprocess
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend
from dapper.adapter.inprocess_bridge import InProcessBridge
from dapper.utils.threadsafe_async import run_coroutine_fire_and_forget_threadsafe

if TYPE_CHECKING:
    from collections.abc import Callable

    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.core.inprocess_debugger import InProcessDebugger

logger = logging.getLogger(__name__)


class _PyDebuggerRuntimeManager:
    """Handles IPC/process/backend runtime primitives for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    def start_ipc_reader(self, *, accept: bool) -> None:
        """Start IPC reader with message handling suitable for selected transport."""

        def _handle_ipc_message(message: dict[str, Any]) -> None:
            """Handle IPC message that may be already parsed (binary) or string."""
            if isinstance(message, dict):
                run_coroutine_fire_and_forget_threadsafe(
                    self._debugger.handle_debug_message(message),
                    self._debugger.loop,
                )
            else:
                self._debugger._handle_debug_message(message)

        self._debugger.ipc.start_reader(_handle_ipc_message, accept=accept)

    def create_external_backend(self) -> None:
        """Create and register the external-process backend."""
        self._debugger._external_backend = ExternalProcessBackend(
            ipc=self._debugger.ipc,
            loop=self._debugger.loop,
            get_process_state=self._debugger._get_process_state,
            pending_commands=self._debugger._session_facade.pending_commands,
            lock=self._debugger.lock,
            get_next_command_id=self._debugger._get_next_command_id,
        )

    def start_debuggee_process(
        self,
        debug_args: list[str],
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        """Start the debuggee process and forward lifecycle/output events."""
        try:
            self._debugger.process = subprocess.Popen(
                debug_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=working_directory,
                env=environment,
            )

            stdout = cast("Any", self._debugger.process.stdout)
            stderr = cast("Any", self._debugger.process.stderr)
            threading.Thread(
                target=self.read_output,
                args=(stdout, "stdout"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self.read_output,
                args=(stderr, "stderr"),
                daemon=True,
            ).start()

            exit_code = self._debugger.process.wait()

            if not self._debugger.is_terminated:
                self._debugger.is_terminated = True

            self._debugger.spawn_threadsafe(
                lambda c=exit_code: self._debugger._handle_program_exit(c),
            )
        except Exception:
            logger.exception("Error starting debuggee")
            self._debugger.is_terminated = True
            self._debugger.spawn_threadsafe(lambda: self._debugger._handle_program_exit(1))

    def read_output(self, stream, category: str) -> None:
        """Read output from debuggee stdout/stderr and forward to DAP output events."""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break

                self._debugger._emit_event("output", {"category": category, "output": line})
        except Exception:
            logger.exception("Error reading %s", category)

    def create_inprocess_bridge(
        self,
        inproc: InProcessDebugger,
        *,
        on_stopped: Callable[[dict[str, Any]], None],
        on_thread: Callable[[dict[str, Any]], None],
        on_exited: Callable[[dict[str, Any]], None],
        on_output: Callable[[str, str], None],
    ) -> None:
        """Create and register the in-process bridge."""
        self._debugger._inproc_bridge = InProcessBridge(
            inproc,
            on_stopped=on_stopped,
            on_thread=on_thread,
            on_exited=on_exited,
            on_output=on_output,
        )

    def create_inprocess_backend(self) -> None:
        """Create and register the in-process backend."""
        if self._debugger._inproc_bridge is None:
            msg = "In-process bridge must be created before backend initialization"
            raise RuntimeError(msg)
        self._debugger._inproc_backend = InProcessBackend(self._debugger._inproc_bridge)
