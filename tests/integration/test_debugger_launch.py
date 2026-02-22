import asyncio
from pathlib import Path
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.config import DapperConfig
from dapper.config import DebuggeeConfig
from dapper.config import IPCConfig
from tests.unit.test_debugger_base import BaseDebuggerTest


# Local async call recorder to replace AsyncMock in tests
class AsyncCallRecorder:
    def __init__(self, side_effect=None, return_value=None):
        self.calls = []
        self.await_count = 0
        self.side_effect = side_effect
        self.return_value = return_value

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.await_count += 1
        if isinstance(self.side_effect, Exception):
            raise self.side_effect
        if callable(self.side_effect):
            return self.side_effect(*args, **kwargs)
        return self.return_value

    @property
    def call_args(self):
        if not self.calls:
            return None
        return self.calls[-1]

    def assert_called_once(self):
        assert len(self.calls) == 1


@pytest.mark.asyncio
class TestDebuggerLaunch(BaseDebuggerTest):
    """Test cases for debugger launch and process management"""

    @patch("subprocess.Popen")
    @patch("threading.Thread")
    async def test_launch_success(self, mock_thread, mock_popen):
        """Test successful launch of a debuggee process"""
        # Create mock streams that behave like file objects
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.readline.side_effect = ["", "", ""]
        mock_stderr.readline.side_effect = ["", "", ""]

        mock_process = MagicMock()
        mock_process.wait.return_value = 0
        mock_process.pid = 12345
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        # Mock the thread to prevent actual thread creation
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        # Mock _start_debuggee_process to prevent hanging
        with patch.object(self.debugger, "_start_debuggee_process") as mock_start:
            mock_start.return_value = None

            # Mock run_in_executor to prevent hanging
            mock_executor = AsyncCallRecorder(return_value=None)
            with patch.object(self.debugger.loop, "run_in_executor", mock_executor):
                # Create a DapperConfig for the launch
                config = DapperConfig(
                    debuggee=DebuggeeConfig(
                        program="python",
                        args=["test.py"],
                        stop_on_entry=False,
                        no_debug=False,
                    ),
                    ipc=IPCConfig(use_binary=True),
                )

                # Should not raise an exception (with timeout)
                await asyncio.wait_for(
                    self.debugger.launch(config),
                    timeout=5.0,  # 5 second timeout
                )

        # Since we mocked run_in_executor, Popen won't be called
        # Instead, verify that the launch method completed without hanging
        assert self.debugger.program_running
        expected_program_path = str(Path("python").resolve())
        assert self.debugger._source_introspection.program_path == expected_program_path

    async def test_launch_with_args(self):
        """Test launch with various arguments"""
        with patch("subprocess.Popen") as mock_popen:
            # Create mock streams
            mock_stdout = MagicMock()
            mock_stderr = MagicMock()
            mock_stdout.readline.side_effect = ["", "", ""]
            mock_stderr.readline.side_effect = ["", "", ""]

            mock_process = MagicMock()
            mock_process.pid = 12346
            mock_process.wait.return_value = 0
            mock_process.stdout = mock_stdout
            mock_process.stderr = mock_stderr
            mock_popen.return_value = mock_process

            # Mock _start_debuggee_process
            with patch.object(self.debugger, "_start_debuggee_process") as mock_start:
                mock_start.return_value = None

                # Mock stopped_event
                mock_wait = AsyncCallRecorder(return_value=None)
                with patch.object(self.debugger.stopped_event, "wait", mock_wait):
                    # Create a DapperConfig for the launch
                    config = DapperConfig(
                        debuggee=DebuggeeConfig(
                            program="python",
                            args=["-m", "pytest", "test.py"],
                            stop_on_entry=True,
                            no_debug=False,
                        ),
                        ipc=IPCConfig(use_binary=True),
                    )

                    await asyncio.wait_for(
                        self.debugger.launch(config),
                        timeout=5.0,  # 5 second timeout
                    )

                    # Check that program is running before shutdown
                    assert self.debugger.program_running
                    expected_program_path = str(Path("python").resolve())
                    assert (
                        self.debugger._source_introspection.program_path == expected_program_path
                    )

                    await self.debugger.shutdown()

            # Since we mocked _start_debuggee_process, Popen won't be called
            # and shutdown is called, program_running should be false
            assert not self.debugger.program_running

    async def test_launch_already_running_error(self):
        """Test launching when already running"""
        # Set up running state
        self.debugger.program_running = True

        # Should raise RuntimeError
        config = DapperConfig(
            debuggee=DebuggeeConfig(
                program="python",
                args=["test.py"],
            ),
            ipc=IPCConfig(use_binary=True),
        )
        with pytest.raises(RuntimeError) as context:
            await self.debugger.launch(config)

        assert "already being debugged" in str(context.value)


if __name__ == "__main__":
    unittest.main()
