import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend

from .test_debugger_base import BaseDebuggerTest


# Local async recorder
class AsyncCallRecorder:
    """
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
        self.debugger.is_terminated = False
        result = await self.debugger.continue_execution(1)

        # Should return failure
        assert not result.get("allThreadsContinued")

    async def test_continue_execution_terminated(self):
        """Test continue_execution when program is terminated"""
        self.debugger.program_running = True
        self.debugger.is_terminated = True

        result = await self.debugger.continue_execution(1)

        # Should return failure
        assert not result.get("allThreadsContinued")

    async def test_continue_execution_clears_stopped_event(self):
        """Test that continue_execution clears the stopped_event"""
        # Set up the debugger state
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Set the stopped event
        self.debugger.stopped_event.set()
        assert self.debugger.stopped_event.is_set()

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.continue_ = AsyncMock(return_value={"allThreadsContinued": True})
        self.debugger._external_backend = mock_backend

        await self.debugger.continue_execution(1)

        # After continue, stopped_event should be cleared
        assert not self.debugger.stopped_event.is_set()

    async def test_next_step(self):
        """Test stepping to next line"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.next_ = AsyncMock()
        self.debugger._external_backend = mock_backend

        await self.debugger.next(1)

        # Should call the backend's next_ method
        mock_backend.next_.assert_called_once_with(1)

    async def test_step_in(self):
        """Test stepping into function"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.step_in = AsyncMock()
        self.debugger._external_backend = mock_backend

        await self.debugger.step_in(1)

        # Should call the backend's step_in method
        mock_backend.step_in.assert_called_once_with(1)

    async def test_step_out(self):
        """Test stepping out of function"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.step_out = AsyncMock()
        self.debugger._external_backend = mock_backend

        await self.debugger.step_out(1)

        # Should call the backend's step_out method
        mock_backend.step_out.assert_called_once_with(1)

    async def test_pause(self):
        """Test pausing execution"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.pause = AsyncMock(return_value=True)
        self.debugger._external_backend = mock_backend

        await self.debugger.pause(1)

        # Should call the backend's pause method
        mock_backend.pause.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
