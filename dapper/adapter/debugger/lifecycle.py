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

    def _resolve_python_executable(self, config: DapperConfig) -> str:
        """Resolve Python executable for launching the debuggee/launcher.

        If ``venv_path`` is configured, treat it as either a virtualenv root
        directory or an explicit Python executable path.
        """
        venv_path = config.debuggee.venv_path
        if not venv_path:
            return sys.executable

        candidate = Path(venv_path)
        if candidate.is_file():
            return str(candidate)

        if os.name == "nt":
            exe = candidate / "Scripts" / "python.exe"
        else:
            exe = candidate / "bin" / "python"

        if exe.exists():
            return str(exe)

        msg = f"Unable to resolve Python interpreter from venvPath: {venv_path}"
        raise RuntimeError(msg)

    def _build_external_launch_args(
        self, config: DapperConfig
    ) -> tuple[list[str], TransportConfig]:
        python_executable = self._resolve_python_executable(config)
        debug_args = [python_executable, "-m", "dapper.launcher.debug_launcher"]

        if config.debuggee.module:
            debug_args.extend(["--module", config.debuggee.module])
        else:
            program_path = self._debugger._source_introspection.program_path
            if not program_path:
                msg = "Program path is not set for program launch"
                raise RuntimeError(msg)
            debug_args.extend(["--program", program_path])

        for search_path in config.debuggee.module_search_paths:
            debug_args.extend(["--module-search-path", search_path])

        for arg in config.debuggee.args:
            debug_args.extend(["--arg", arg])

        if config.debuggee.stop_on_entry:
            debug_args.append("--stop-on-entry")
        if config.debuggee.no_debug:
            debug_args.append("--no-debug")
        if not config.just_my_code:
            debug_args.append("--no-just-my-code")
        if config.strict_expression_watch_policy:
            debug_args.append("--strict-expression-watch-policy")
        if config.subprocess_auto_attach:
            debug_args.append("--subprocess-auto-attach")

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

        return debug_args, transport_config

    async def _start_external_process(
        self,
        debug_args: list[str],
        *,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        use_legacy_signature = working_directory is None and environment is None
        if self._debugger.is_test_mode_enabled():
            start_target = self._debugger._start_debuggee_process
            if use_legacy_signature:
                threading.Thread(
                    target=start_target,
                    args=(debug_args,),
                    daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=start_target,
                    kwargs={
                        "debug_args": debug_args,
                        "working_directory": working_directory,
                        "environment": environment,
                    },
                    daemon=True,
                ).start()
            return

        if use_legacy_signature:
            try:
                await self._debugger.loop.run_in_executor(
                    None,
                    self._debugger._start_debuggee_process,
                    debug_args,
                )
            except Exception:
                await asyncio.to_thread(
                    self._debugger._start_debuggee_process,
                    debug_args,
                )
            return

        try:
            await self._debugger.loop.run_in_executor(
                None,
                self._debugger._start_debuggee_process,
                debug_args,
                working_directory,
                environment,
            )
        except Exception:
            await asyncio.to_thread(
                self._debugger._start_debuggee_process,
                debug_args,
                working_directory,
                environment,
            )

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        config.validate()

        if self._debugger.program_running:
            msg = "A program is already being debugged"
            raise RuntimeError(msg)

        if config.debuggee.program:
            self._debugger._source_introspection.program_path = str(
                Path(config.debuggee.program).resolve()
            )
        else:
            self._debugger._source_introspection.program_path = config.debuggee.module
        self._debugger.stop_on_entry = config.debuggee.stop_on_entry
        self._debugger.no_debug = config.debuggee.no_debug
        self._debugger.in_process = config.in_process

        if config.in_process:
            await self.launch_in_process(config)
            return

        self._debugger.enable_ipc_mode()
        debug_args, _transport_config = self._build_external_launch_args(config)

        logger.info("Launching program: %s", self._debugger._source_introspection.program_path)
        logger.debug("Debug command: %s", " ".join(debug_args))

        process_env = None
        if config.debuggee.environment or config.debuggee.module_search_paths:
            process_env = dict(os.environ)
            process_env.update(config.debuggee.environment)
            if config.debuggee.module_search_paths:
                existing = process_env.get("PYTHONPATH", "")
                merged = os.pathsep.join(config.debuggee.module_search_paths)
                process_env["PYTHONPATH"] = (
                    f"{merged}{os.pathsep}{existing}" if existing else merged
                )

        await self._start_external_process(
            debug_args,
            working_directory=config.debuggee.working_directory,
            environment=process_env,
        )

        if self._debugger.ipc.is_enabled:
            self._debugger.start_ipc_reader(accept=True)

        self._debugger.create_external_backend()

        self._debugger.program_running = True

        process_name = (
            Path(self._debugger._source_introspection.program_path).name
            if config.debuggee.program
            else config.debuggee.module
        )
        process_event = {
            "name": process_name,
            "systemProcessId": self._debugger.process.pid if self._debugger.process else None,
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self._debugger.server.send_event("process", process_event)

        if self._debugger.stop_on_entry and not self._debugger.no_debug:
            await self._debugger.await_stop_event()

    async def launch_in_process(self, config: DapperConfig) -> None:
        """Initialize in-process debugging bridge and emit process event."""
        self._debugger.in_process = True
        inproc = InProcessDebugger(
            just_my_code=config.just_my_code,
            strict_expression_watch_policy=config.strict_expression_watch_policy,
        )
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
            "name": Path(self._debugger._source_introspection.program_path or "").name,
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
                "name": self._debugger._source_introspection.program_path or "attached",
                "isLocalProcess": True,
                "startMethod": "attach",
            },
        )
