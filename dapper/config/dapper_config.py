"""Centralized configuration management for Dapper debug adapter.

This module provides a unified configuration system that replaces scattered
configuration handling throughout the codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from dapper.errors import ConfigurationError

if TYPE_CHECKING:
    from dapper.protocol.requests import AttachRequest
    from dapper.protocol.requests import LaunchRequest


@dataclass
class IPCConfig:
    """IPC transport configuration."""
    
    transport: Literal["auto", "pipe", "unix", "tcp"] = "auto"
    host: str = "127.0.0.1"
    port: int | None = None
    path: str | None = None
    pipe_name: str | None = None
    use_binary: bool = True
    
    def __post_init__(self) -> None:
        """Set defaults based on platform and transport type."""
        if self.transport == "auto":
            self.transport = "pipe" if os.name == "nt" else "unix"


@dataclass
class DebuggeeConfig:
    """Debuggee process configuration."""
    
    program: str = ""
    args: list[str] = field(default_factory=list)
    stop_on_entry: bool = False
    no_debug: bool = False
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class DapperConfig:
    """Centralized configuration for Dapper debug adapter.
    
    This configuration consolidates all settings that were previously
    scattered across multiple components and request handlers.
    """
    
    # Mode selection
    mode: Literal["launch", "attach", "inprocess"] = "launch"
    in_process: bool = False
    
    # Component configurations
    ipc: IPCConfig = field(default_factory=IPCConfig)
    debuggee: DebuggeeConfig = field(default_factory=DebuggeeConfig)
    
    # Advanced options
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    enable_metrics: bool = False
    timeout_seconds: int = 30
    
    @classmethod
    def from_launch_request(cls, request: LaunchRequest) -> DapperConfig:
        """Create config from launch request arguments."""
        args = request.get("arguments", {})
        
        # Debuggee configuration
        debuggee = DebuggeeConfig(
            program=args.get("program", ""),
            args=args.get("args", []),
            stop_on_entry=args.get("stopOnEntry", False),
            no_debug=args.get("noDebug", False),
            working_directory=args.get("cwd"),
            environment=args.get("env", {}),
        )
        
        # IPC configuration
        ipc = IPCConfig(
            transport=args.get("ipcTransport", "auto"),
            pipe_name=args.get("ipcPipeName"),
            use_binary=args.get("useBinaryIpc", True),
        )
        
        return cls(
            mode="launch",
            in_process=args.get("inProcess", False),
            debuggee=debuggee,
            ipc=ipc,
        )
    
    @classmethod
    def from_attach_request(cls, request: AttachRequest) -> DapperConfig:
        """Create config from attach request arguments."""
        args = request.get("arguments", {})
        
        # IPC configuration for attach
        ipc = IPCConfig(
            transport=args.get("ipcTransport", "auto"),
            host=args.get("ipcHost", "127.0.0.1"),
            port=args.get("ipcPort"),
            path=args.get("ipcPath"),
            pipe_name=args.get("ipcPipeName"),
            use_binary=args.get("useBinaryIpc", True),
        )
        
        return cls(
            mode="attach",
            ipc=ipc,
        )
    
    def validate(self) -> None:
        """Validate configuration and raise errors for invalid setups."""
        if self.in_process and self.mode == "attach":
            raise ConfigurationError(
                "In-process mode is not compatible with attach",
                config_key="in_process",
                details={"mode": self.mode, "in_process": self.in_process},
            )
        
        if self.mode == "launch" and not self.debuggee.program:
            raise ConfigurationError(
                "Program path is required for launch mode",
                config_key="program",
                details={"mode": self.mode},
            )
        
        if self.mode == "attach":
            if self.ipc.transport == "tcp" and not self.ipc.port:
                raise ConfigurationError(
                    "Port is required for TCP attach",
                    config_key="ipc_port",
                    details={"transport": self.ipc.transport},
                )
            if self.ipc.transport == "unix" and not self.ipc.path:
                raise ConfigurationError(
                    "Path is required for Unix socket attach",
                    config_key="ipc_path",
                    details={"transport": self.ipc.transport},
                )
            if self.ipc.transport == "pipe" and not self.ipc.pipe_name:
                raise ConfigurationError(
                    "Pipe name is required for named pipe attach",
                    config_key="ipc_pipe_name",
                    details={"transport": self.ipc.transport},
                )
    
    def to_launch_kwargs(self) -> dict[str, Any]:
        """Convert to keyword arguments for debugger.launch()."""
        kwargs = {
            "program": self.debuggee.program,
            "args": self.debuggee.args,
            "stop_on_entry": self.debuggee.stop_on_entry,
            "no_debug": self.debuggee.no_debug,
            "in_process": self.in_process,
            "use_binary_ipc": self.ipc.use_binary,
        }
        
        # Add IPC-specific kwargs
        if self.ipc.transport != "auto":
            kwargs["ipc_transport"] = self.ipc.transport
        if self.ipc.pipe_name:
            kwargs["ipc_pipe_name"] = self.ipc.pipe_name
        
        return kwargs
    
    def to_attach_kwargs(self) -> dict[str, Any]:
        """Convert to keyword arguments for debugger.attach()."""
        return {
            "use_ipc": True,
            "ipc_transport": self.ipc.transport,
            "ipc_host": self.ipc.host,
            "ipc_port": self.ipc.port,
            "ipc_path": self.ipc.path,
            "ipc_pipe_name": self.ipc.pipe_name,
        }


# Default configuration instance
DEFAULT_CONFIG = DapperConfig()
