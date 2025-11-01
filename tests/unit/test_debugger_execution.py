import unittest
from unittest.mock import patch

import pytest

from .test_debugger_base import BaseDebuggerTest


# Local async recorder
class AsyncCallRecorder:
    """

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Replacement for AsyncMock used in these tests.

    Records calls synchronously and returns a noop coroutine so callers can
    safely await the result without creating orphaned coroutine warnings.
    """

    def __init__(self, side_effect=None, return_value=None):
        self.calls: list[tuple[tuple, dict]] = []
        self.call_args = None
        self.side_effect = side_effect
        self.return_value = return_value

    def __call__(self, *args, **kwargs):
        # Record the call synchronously so tests can inspect it immediately.
        self.calls.append((args, kwargs))
        self.call_args = (args, kwargs)

        async def _noop():
            if isinstance(self.side_effect, Exception):
                raise self.side_effect
            if callable(self.side_effect):
                return self.side_effect(*args, **kwargs)
            return self.return_value

        return _noop()

    def assert_called_once(self):
        assert len(self.calls) == 1, f"expected 1 call, got {len(self.calls)}"


@pytest.mark.asyncio
class TestDebuggerExecution(BaseDebuggerTest):
    """Test cases for debugger execution control"""

    async def test_continue_execution_not_running(self):
        """Test continue_execution when program is not running"""
        self.debugger.program_running = False

        result = await self.debugger.continue_execution(1)

        # Should return failure
        assert not result["allThreadsContinued"]

    async def test_continue_execution_terminated(self):
        """Test continue_execution when program is terminated"""
        self.debugger.program_running = True
        self.debugger.is_terminated = True

        result = await self.debugger.continue_execution(1)

        # Should return failure
        assert not result["allThreadsContinued"]

    async def test_continue_execution_clears_stopped_event(self):
        """Test that continue_execution clears the stopped_event"""
        # Set up the debugger state
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Set the stopped event
        self.debugger.stopped_event.set()
        assert self.debugger.stopped_event.is_set()

        # Mock the command sending
        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ):
            await self.debugger.continue_execution(1)

        # After continue, stopped_event should be cleared
        assert not self.debugger.stopped_event.is_set()

    async def test_next_step(self):
        """Test stepping to next line"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            await self.debugger.next(1)

            # Should send next command
            mock_send.assert_called_once()
            assert mock_send.call_args is not None
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "next"
            assert call_args["arguments"]["threadId"] == 1

    async def test_step_in(self):
        """Test stepping into function"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            await self.debugger.step_in(1)

            # Should send stepIn command
            mock_send.assert_called_once()
            assert mock_send.call_args is not None
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "stepIn"
            assert call_args["arguments"]["threadId"] == 1

    async def test_step_out(self):
        """Test stepping out of function"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            await self.debugger.step_out(1)

            # Should send stepOut command
            mock_send.assert_called_once()
            assert mock_send.call_args is not None
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "stepOut"
            assert call_args["arguments"]["threadId"] == 1

    async def test_pause(self):
        """Test pausing execution"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            await self.debugger.pause(1)

            # Should send pause command
            mock_send.assert_called_once()
            assert mock_send.call_args is not None
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "pause"
            assert call_args["arguments"]["threadId"] == 1


if __name__ == "__main__":
    unittest.main()
