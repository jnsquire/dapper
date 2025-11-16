import asyncio
from unittest.mock import MagicMock

from dapper.server import PyDebugger


class BaseDebuggerTest:
    """Base test class with common debugger setup"""

    def setup_method(self):
        """Set up for each test"""
        self.mock_server = MagicMock()

        class _CompletedAwaitable:
            def __init__(self, result=None):
                self._result = result

            def __await__(self):
                async def _c():
                    return self._result

                return _c().__await__()

        class AsyncRecorder:
            def __init__(self):
                self.calls = []

            def __call__(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return _CompletedAwaitable()

        self.mock_server.send_event = AsyncRecorder()
        # Create a dedicated fresh loop for isolation (avoids deprecated get_event_loop)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.debugger = PyDebugger(self.mock_server, self.loop)

    def teardown_method(self):
        """Clean up after each test"""
        if hasattr(self, "debugger") and self.debugger:
            # Shutdown the debugger - no need to close loop since we're
            # using current
            self.loop.run_until_complete(self.debugger.shutdown())
        # Close and unset the loop to avoid leakage across tests
        try:
            self.loop.close()
        finally:
            try:
                asyncio.set_event_loop(None)  # type: ignore[arg-type]
            except Exception:
                pass
