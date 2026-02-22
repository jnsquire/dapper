"""Tests for the centralized Dapper configuration system."""

import os
from typing import TYPE_CHECKING
from typing import cast

import pytest

from dapper.config import DapperConfig
from dapper.config import DebuggeeConfig
from dapper.config import IPCConfig
from dapper.errors import ConfigurationError

if TYPE_CHECKING:
    from dapper.protocol.requests import AttachRequest
    from dapper.protocol.requests import LaunchRequest


class TestDapperConfig:
    """Test cases for DapperConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = DapperConfig()

        assert config.mode == "launch"
        assert config.in_process is False
        assert config.strict_expression_watch_policy is False
        assert config.subprocess_auto_attach is False
        # Transport is resolved from "auto" based on platform
        expected_transport = "pipe" if os.name == "nt" else "unix"
        assert config.ipc.transport == expected_transport
        assert config.ipc.use_binary is True
        assert config.debuggee.program == ""
        assert config.debuggee.args == []

    def test_from_launch_request_minimal(self) -> None:
        """Test creating config from minimal launch request."""
        request: LaunchRequest = {
            "seq": 1,
            "command": "launch",
            "type": "request",
            "arguments": {"program": "/path/to/program.py", "noDebug": False, "args": []},
        }
        config = DapperConfig.from_launch_request(request)

        assert config.mode == "launch"
        assert config.debuggee.program == "/path/to/program.py"
        assert config.debuggee.args == []
        assert config.debuggee.stop_on_entry is False
        assert config.debuggee.no_debug is False
        assert config.in_process is False

    def test_from_launch_request_full(self) -> None:
        """Test creating config from full launch request."""
        request = cast(
            "LaunchRequest",
            {
                "seq": 1,
                "command": "launch",
                "type": "request",
                "arguments": {
                    "program": "/path/to/program.py",
                    "args": ["--verbose", "--debug"],
                    "noDebug": False,
                    "stopOnEntry": True,
                    "inProcess": True,
                    "strictExpressionWatchPolicy": True,
                    "subprocessAutoAttach": True,
                    "useBinaryIpc": False,
                    "ipcTransport": "tcp",
                    "ipcPipeName": "test-pipe",
                    "cwd": "/working/dir",
                    "env": {"PATH": "/custom/path"},
                },
            },
        )
        config = DapperConfig.from_launch_request(request)

        assert config.mode == "launch"
        assert config.debuggee.program == "/path/to/program.py"
        assert config.debuggee.args == ["--verbose", "--debug"]
        assert config.debuggee.stop_on_entry is True
        assert config.debuggee.no_debug is False
        assert config.in_process is True
        assert config.strict_expression_watch_policy is True
        assert config.subprocess_auto_attach is True
        assert config.ipc.transport == "tcp"
        assert config.ipc.use_binary is False
        assert config.ipc.pipe_name == "test-pipe"
        assert config.debuggee.working_directory == "/working/dir"
        assert config.debuggee.environment == {"PATH": "/custom/path"}

    def test_from_attach_request(self) -> None:
        """Test creating config from attach request."""
        request = cast(
            "AttachRequest",
            {
                "seq": 1,
                "command": "attach",
                "type": "request",
                "arguments": {
                    "ipcTransport": "tcp",
                    "ipcHost": "localhost",
                    "ipcPort": 4711,
                    "useBinaryIpc": True,
                    "strictExpressionWatchPolicy": True,
                },
            },
        )

        config = DapperConfig.from_attach_request(request)

        assert config.mode == "attach"
        assert config.ipc.transport == "tcp"
        assert config.ipc.host == "localhost"
        assert config.ipc.port == 4711
        assert config.ipc.use_binary is True
        assert config.strict_expression_watch_policy is True

    def test_validate_launch_missing_program(self) -> None:
        """Test validation fails when program is missing for launch."""
        config = DapperConfig(mode="launch")

        with pytest.raises(ConfigurationError, match="Program path is required"):
            config.validate()

    def test_validate_attach_tcp_missing_port(self) -> None:
        """Test validation fails when port is missing for TCP attach."""
        config = DapperConfig(mode="attach")
        config.ipc.transport = "tcp"
        config.ipc.port = None

        with pytest.raises(ConfigurationError, match="Port is required for TCP attach"):
            config.validate()

    def test_validate_attach_unix_missing_path(self) -> None:
        """Test validation fails when path is missing for Unix attach."""
        config = DapperConfig(mode="attach")
        config.ipc.transport = "unix"
        config.ipc.path = None

        with pytest.raises(ConfigurationError, match="Path is required for Unix socket attach"):
            config.validate()

    def test_validate_attach_pipe_missing_name(self) -> None:
        """Test validation fails when pipe name is missing for pipe attach."""
        config = DapperConfig(mode="attach")
        config.ipc.transport = "pipe"
        config.ipc.pipe_name = None

        with pytest.raises(
            ConfigurationError,
            match="Pipe name is required for named pipe attach",
        ):
            config.validate()

    def test_validate_in_process_attach_incompatible(self) -> None:
        """Test validation fails when in_process is used with attach."""
        config = DapperConfig(mode="attach", in_process=True)

        with pytest.raises(
            ConfigurationError,
            match="In-process mode is not compatible with attach",
        ):
            config.validate()

    def test_to_launch_kwargs(self) -> None:
        """Test converting config to launch kwargs."""
        config = DapperConfig()
        config.debuggee.program = "test.py"
        config.debuggee.args = ["--verbose"]
        config.debuggee.stop_on_entry = True
        config.debuggee.no_debug = False
        config.in_process = True
        config.subprocess_auto_attach = True
        config.ipc.transport = "tcp"
        config.ipc.pipe_name = "test-pipe"
        config.ipc.use_binary = False

        kwargs = config.to_launch_kwargs()

        expected = {
            "program": "test.py",
            "args": ["--verbose"],
            "stopOnEntry": True,
            "noDebug": False,
            "inProcess": True,
            "useBinaryIpc": False,
            "subprocessAutoAttach": True,
            "ipcTransport": "tcp",
            "ipcPipeName": "test-pipe",
        }

        assert kwargs == expected

    def test_to_attach_kwargs(self) -> None:
        """Test converting config to attach kwargs."""
        config = DapperConfig(mode="attach")
        config.ipc.transport = "tcp"
        config.ipc.host = "localhost"
        config.ipc.port = 4711
        config.ipc.path = "/tmp/socket"
        config.ipc.pipe_name = "test-pipe"

        kwargs = config.to_attach_kwargs()

        expected = {
            "useIpc": True,
            "ipcTransport": "tcp",
            "ipcHost": "localhost",
            "ipcPort": 4711,
            "ipcPath": "/tmp/socket",
            "ipcPipeName": "test-pipe",
        }

        assert kwargs == expected


class TestIPCConfig:
    """Test cases for IPCConfig class."""

    def test_auto_transport_selection(self) -> None:
        """Test automatic transport selection based on platform."""
        # Test with Windows-like environment
        with pytest.MonkeyPatch().context() as m:
            m.setattr(os, "name", "nt")
            ipc = IPCConfig(transport="auto")
            assert ipc.transport == "pipe"

        # Test with Unix-like environment
        with pytest.MonkeyPatch().context() as m:
            m.setattr(os, "name", "posix")
            ipc = IPCConfig(transport="auto")
            assert ipc.transport == "unix"


class TestDebuggeeConfig:
    """Test cases for DebuggeeConfig class."""

    def test_default_values(self) -> None:
        """Test default debuggee configuration."""
        debuggee = DebuggeeConfig()

        assert debuggee.program == ""
        assert debuggee.args == []
        assert debuggee.stop_on_entry is False
        assert debuggee.no_debug is False
        assert debuggee.working_directory is None
        assert debuggee.environment == {}
