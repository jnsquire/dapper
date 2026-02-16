"""Centralized configuration management for Dapper debug adapter.

This module provides a unified configuration system that replaces scattered
configuration handling throughout the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypeVar

from dapper.errors import ConfigurationError

if TYPE_CHECKING:
    from dapper.protocol.requests import AttachRequest
    from dapper.protocol.requests import LaunchRequest

T = TypeVar("T")


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

        def _get(key: str, default: T) -> T:
            # Prefer value present under the canonical camelCase key; if value is
            # explicitly None, fall back to default. Type is inferred from default.
            if key in args:
                v = args.get(key)
                return default if v is None else v  # type: ignore[return-value]
            return default

        # Debuggee configuration
        debuggee = DebuggeeConfig(
            program=_get("program", default=""),
            args=_get("args", default=[]),
            stop_on_entry=_get("stopOnEntry", default=False),
            no_debug=_get("noDebug", default=False),
            working_directory=_get("cwd", default=None),
            environment=_get("env", default={}),
        )

        # IPC configuration
        # Type: ignore needed because Literal type cannot be perfectly inferred from string default
        ipc = IPCConfig(
            transport=_get("ipcTransport", default="auto"),
            pipe_name=_get("ipcPipeName", default=None),
            use_binary=_get("useBinaryIpc", default=True),
        )

        return cls(
            mode="launch",
            in_process=_get("inProcess", default=False),
            debuggee=debuggee,
            ipc=ipc,
        )

    @classmethod
    def from_attach_request(cls, request: AttachRequest) -> DapperConfig:
        """Create config from attach request arguments."""
        args = request.get("arguments", {})

        def _get_attach(key: str, default: T) -> T:
            # Normalize to the same camelCase-only convention for attach args.
            # Type is inferred from default.
            if key in args:
                v = args.get(key)
                return default if v is None else v  # type: ignore[return-value]
            return default

        # IPC configuration for attach
        # Type: ignore needed because Literal type cannot be perfectly inferred from string default
        ipc = IPCConfig(
            transport=_get_attach("ipcTransport", default="auto"),
            host=_get_attach("ipcHost", default="127.0.0.1"),
            port=_get_attach("ipcPort", default=None),
            path=_get_attach("ipcPath", default=None),
            pipe_name=_get_attach("ipcPipeName", default=None),
            use_binary=_get_attach("useBinaryIpc", default=True),
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
            "stopOnEntry": self.debuggee.stop_on_entry,
            "noDebug": self.debuggee.no_debug,
            "inProcess": self.in_process,
            "useBinaryIpc": self.ipc.use_binary,
        }

        # Add IPC-specific kwargs
        if self.ipc.transport != "auto":
            kwargs["ipcTransport"] = self.ipc.transport
        if self.ipc.pipe_name:
            kwargs["ipcPipeName"] = self.ipc.pipe_name

        return kwargs

    def to_attach_kwargs(self) -> dict[str, Any]:
        """Convert to keyword arguments for debugger.attach()."""
        return {
            "useIpc": True,
            "ipcTransport": self.ipc.transport,
            "ipcHost": self.ipc.host,
            "ipcPort": self.ipc.port,
            "ipcPath": self.ipc.path,
            "ipcPipeName": self.ipc.pipe_name,
        }


# Default configuration instance
# Use an attach-mode default so the default config passes validation
DEFAULT_CONFIG = DapperConfig(mode="attach")
