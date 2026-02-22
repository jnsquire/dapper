"""
Subprocess debugging manager for Dapper.

This module provides the infrastructure for automatically detecting and attaching
to child processes spawned by the debuggee. It works by monkey-patching Python's
subprocess/multiprocessing APIs to inject the dapper debug launcher into child
processes.

Architecture:
    1. When subprocess debugging is enabled, SubprocessManager patches:
       - subprocess.Popen
       - multiprocessing.Process
       - os.execv/execve (when running Python)
    
    2. Each child process is launched with dapper's debug_launcher prepended,
       configured to connect back to the parent's IPC server on a new port.
    
    3. The SubprocessManager notifies the VS Code extension via a custom event
       ('dapper/childProcess') so it can spawn a new debug session for the child.

Usage:
    manager = SubprocessManager(debugger, send_event, ipc_config)
    manager.enable()  # Patches subprocess APIs
    # ... debugging happens ...
    manager.disable()  # Restores original APIs

Status: SCAFFOLD — not yet fully implemented. The detection and notification
        framework is in place; the actual patching logic needs to be completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ChildProcessInfo:
    """Information about a detected child process."""
    pid: int
    name: str
    ipc_port: int
    command: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    is_python: bool = False
    parent_pid: int = 0
    session_id: str | None = None


@dataclass 
class SubprocessConfig:
    """Configuration for subprocess debugging."""
    enabled: bool = False
    auto_attach: bool = True
    max_children: int = 10
    ipc_host: str = "localhost"
    ipc_port_range: tuple[int, int] = (5700, 5799)
    debug_options: list[str] = field(default_factory=list)


class SubprocessManager:
    """Manages detection and debugging of child processes.
    
    This manager can be installed on a running debugger to intercept
    subprocess creation and automatically attach the debugger to child
    processes.
    """

    def __init__(
        self,
        send_event: Callable[[str, dict], None],
        config: SubprocessConfig | None = None,
    ):
        self._send_event = send_event
        self._config = config or SubprocessConfig()
        self._children: dict[int, ChildProcessInfo] = {}
        self._next_port = self._config.ipc_port_range[0]
        self._lock = threading.Lock()
        self._enabled = False
        self._original_popen = None
        self._original_mp_process = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def children(self) -> dict[int, ChildProcessInfo]:
        return dict(self._children)

    @property
    def config(self) -> SubprocessConfig:
        """Return subprocess manager configuration."""
        return self._config

    def is_python_command(self, args: list[str]) -> bool:
        """Public wrapper for Python command detection."""
        return self._is_python_command(args)

    def allocate_port(self) -> int:
        """Public wrapper for allocating an IPC port."""
        return self._allocate_port()

    def build_launcher_args(self, original_args: list[str], port: int) -> list[str]:
        """Public wrapper for launcher argument construction."""
        return self._build_launcher_args(original_args, port)

    def enable(self) -> None:
        """Enable subprocess detection by patching subprocess APIs."""
        if self._enabled:
            return
        
        if not self._config.enabled:
            logger.debug("Subprocess debugging is disabled in config")
            return
        
        logger.info("Enabling subprocess debugging")
        self._patch_subprocess()
        self._enabled = True

    def disable(self) -> None:
        """Disable subprocess detection and restore original APIs."""
        if not self._enabled:
            return
        
        logger.info("Disabling subprocess debugging")
        self._unpatch_subprocess()
        self._enabled = False

    def on_child_detected(self, info: ChildProcessInfo) -> None:
        """Called when a new child process is detected.
        
        Notifies the VS Code extension so it can start a new debug session.
        """
        with self._lock:
            if len(self._children) >= self._config.max_children:
                logger.warning(
                    f"Maximum child process limit ({self._config.max_children}) reached, "
                    f"ignoring child process {info.pid}"
                )
                return
            
            self._children[info.pid] = info
        
        logger.info(f"Child process detected: pid={info.pid}, name={info.name}")
        
        # Notify the extension
        self._send_event("dapper/childProcess", {
            "pid": info.pid,
            "name": info.name,
            "ipcPort": info.ipc_port,
            "command": info.command,
            "cwd": info.cwd,
            "isPython": info.is_python,
            "parentPid": info.parent_pid,
            "sessionId": info.session_id,
        })

    def on_child_exited(self, pid: int) -> None:
        """Called when a child process exits."""
        with self._lock:
            child = self._children.pop(pid, None)
        
        if child:
            logger.info(f"Child process exited: pid={pid}, name={child.name}")
            self._send_event("dapper/childProcessExited", {
                "pid": pid,
                "name": child.name,
            })

    def _allocate_port(self) -> int:
        """Allocate the next available IPC port for a child process."""
        with self._lock:
            port = self._next_port
            self._next_port += 1
            if self._next_port > self._config.ipc_port_range[1]:
                self._next_port = self._config.ipc_port_range[0]
            return port

    def _is_python_command(self, args: list[str]) -> bool:
        """Check if the command appears to be running a Python interpreter."""
        if not args:
            return False
        cmd = Path(args[0]).name.lower()
        return cmd in ("python", "python3", "python.exe", "python3.exe") or \
               cmd.startswith("python3.")

    def _build_launcher_args(self, original_args: list[str], port: int) -> list[str]:
        """Build the command line to launch a child process with dapper attached.
        
        Prepends the dapper debug_launcher module to the original command.
        """
        python_exe = original_args[0] if original_args else sys.executable
        
        launcher_args = [
            python_exe,
            "-m", "dapper.debug_launcher",
            "--ipc", "tcp",
            "--ipc-port", str(port),
            "--ipc-binary",
            "--subprocess",
            "--program",
        ]
        
        # Find the actual script/module in the original args (skip python flags)
        script_idx = 1
        for i, arg in enumerate(original_args[1:], start=1):
            if not arg.startswith("-"):
                script_idx = i
                break
        
        # Add the original program and its arguments
        launcher_args.extend(original_args[script_idx:])
        
        return launcher_args

    def _patch_subprocess(self) -> None:
        """Monkey-patch subprocess.Popen to intercept child process creation.
        
        TODO: Implement the actual patching. This is a scaffold.
        """
        self._original_popen = subprocess.Popen.__init__
        
        manager = self  # Capture reference for closure
        original_init = self._original_popen
        
        def patched_popen_init(self_popen, args, **kwargs):
            """Patched Popen.__init__ that intercepts Python subprocess creation."""
            # Convert args to list if string
            if isinstance(args, str):
                args_list = shlex.split(args)
            elif isinstance(args, (list, tuple)):
                args_list = list(args)
            else:
                args_list = [str(args)]
            
            if manager.config.auto_attach and manager.is_python_command(args_list):
                port = manager.allocate_port()
                new_args = manager.build_launcher_args(args_list, port)
                logger.debug(f"Intercepted subprocess: {args_list} -> {new_args}")
                
                # Call original with modified args
                original_init(self_popen, new_args, **kwargs)
                
                # Notify about the new child
                child_info = ChildProcessInfo(
                    pid=self_popen.pid,
                    name=Path(args_list[-1]).name if args_list else "unknown",
                    ipc_port=port,
                    command=args_list,
                    cwd=kwargs.get("cwd"),
                    is_python=True,
                    parent_pid=os.getpid(),
                )
                manager.on_child_detected(child_info)
            else:
                original_init(self_popen, args, **kwargs)

        subprocess.Popen.__init__ = patched_popen_init  # type: ignore[method-assign]
        logger.debug("Patched subprocess.Popen")

    def _unpatch_subprocess(self) -> None:
        """Restore original subprocess.Popen."""

        if self._original_popen is not None:
            subprocess.Popen.__init__ = self._original_popen  # type: ignore[method-assign]
            self._original_popen = None
            logger.debug("Restored subprocess.Popen")

    def cleanup(self) -> None:
        """Clean up all resources."""
        self.disable()
        with self._lock:
            self._children.clear()
