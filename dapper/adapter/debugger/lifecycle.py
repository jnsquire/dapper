from __future__ import annotations

# ruff: noqa: SLF001
import asyncio
import logging
import os
from pathlib import Path
import sys
import threading
from typing import TYPE_CHECKING

from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.ipc import TransportConfig

if TYPE_CHECKING:
    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.config import DapperConfig

logger = logging.getLogger(__name__)


class _PyDebuggerLifecycleManager:
    """Handles launch/attach lifecycle orchestration for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        config.validate()

        if self._debugger.program_running:
            msg = "A program is already being debugged"
            raise RuntimeError(msg)

        self._debugger.program_path = str(Path(config.debuggee.program).resolve())
        self._debugger.stop_on_entry = config.debuggee.stop_on_entry
        self._debugger.no_debug = config.debuggee.no_debug
        self._debugger.in_process = config.in_process

        if config.in_process:
            await self.launch_in_process()
            return

        debug_args = [
            sys.executable,
            "-m",
            "dapper.launcher.debug_launcher",
            "--program",
            self._debugger.program_path,
        ]

        for arg in config.debuggee.args:
            debug_args.extend(["--arg", arg])

        if config.debuggee.stop_on_entry:
            debug_args.append("--stop-on-entry")

        if config.debuggee.no_debug:
            debug_args.append("--no-debug")

        if not config.just_my_code:
            debug_args.append("--no-just-my-code")

        self._debugger.enable_ipc_mode()

        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary,
        )

        debug_args.extend(self._debugger.ipc.create_listener(config=transport_config))
        if transport_config.use_binary:
            debug_args.append("--ipc-binary")

        logger.info("Launching program: %s", self._debugger.program_path)
        logger.debug("Debug command: %s", " ".join(debug_args))

        if self._debugger.is_test_mode_enabled():
            threading.Thread(
                target=self._debugger._start_debuggee_process,
                args=(debug_args,),
                daemon=True,
            ).start()
        else:
            try:
                await self._debugger.loop.run_in_executor(
                    None,
                    self._debugger._start_debuggee_process,
                    debug_args,
                )
            except Exception:
                await asyncio.to_thread(self._debugger._start_debuggee_process, debug_args)

        if self._debugger.ipc.is_enabled:
            self._debugger.start_ipc_reader(accept=True)

        self._debugger.create_external_backend()

        self._debugger.program_running = True

        process_event = {
            "name": Path(self._debugger.program_path).name,
            "systemProcessId": self._debugger.process.pid if self._debugger.process else None,
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self._debugger.server.send_event("process", process_event)

        if self._debugger.stop_on_entry and not self._debugger.no_debug:
            await self._debugger.await_stop_event()

    async def launch_in_process(self) -> None:
        """Initialize in-process debugging bridge and emit process event."""
        self._debugger.in_process = True
        inproc = InProcessDebugger()
        self._debugger.create_inprocess_bridge(
            inproc,
            on_stopped=self._debugger.handle_event_stopped,
            on_thread=self._debugger.handle_event_thread,
            on_exited=self._debugger.handle_event_exited,
            on_output=self._debugger.handle_inprocess_output,
        )
        self._debugger.create_inprocess_backend()

        self._debugger.program_running = True
        proc_event = {
            "name": Path(self._debugger.program_path or "").name,
            "systemProcessId": os.getpid(),
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self._debugger.server.send_event("process", proc_event)

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an already running debuggee via IPC using centralized configuration."""
        config.validate()

        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary,
        )

        self._debugger.ipc.connect(transport_config)
        self._debugger.start_ipc_reader(accept=False)
        self._debugger.create_external_backend()

        self._debugger.program_running = True
        await self._debugger.server.send_event(
            "process",
            {
                "name": self._debugger.program_path or "attached",
                "isLocalProcess": True,
                "startMethod": "attach",
            },
        )
