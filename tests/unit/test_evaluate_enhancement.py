import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.server import PyDebugger


@pytest.mark.asyncio
async def test_evaluate_with_response():
    """

    from pathlib import Path

    # Add the project root to the Python path
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:

    Return the debuggee-provided body when a response exists."""
    server = Mock()
    server.send_event = AsyncMock()

    dbg = PyDebugger(server)
    dbg.loop = asyncio.get_running_loop()
    dbg.process = Mock()
    dbg.is_terminated = False

    expected_body = {"result": "42", "type": "int", "variablesReference": 0}

    # Create a mock backend
    mock_backend = MagicMock(spec=ExternalProcessBackend)
    mock_backend.evaluate = AsyncMock(return_value=expected_body)
    dbg._external_backend = mock_backend

    res = await dbg.evaluate("x + 1", frame_id=1, context="watch")
    assert res == expected_body


@pytest.mark.asyncio
async def test_evaluate_without_response():
    """evaluate() should fall back gracefully when debuggee doesn't respond.

    Note: The fallback logic is now in ExternalProcessBackend, not in PyDebugger.
    This test verifies that the external backend's fallback is used.
    """
    server = Mock()
    server.send_event = AsyncMock()

    dbg = PyDebugger(server)
    dbg.loop = asyncio.get_running_loop()
    dbg.process = Mock()
    dbg.is_terminated = False

    # Create a mock backend that returns the fallback response (simulating
    # what ExternalProcessBackend does when the debuggee doesn't respond)
    expr = "x + 1"
    fallback_response = {
        "result": f"<evaluation of '{expr}' not available>",
        "type": "string",
        "variablesReference": 0,
    }
    mock_backend = MagicMock(spec=ExternalProcessBackend)
    mock_backend.evaluate = AsyncMock(return_value=fallback_response)
    dbg._external_backend = mock_backend

    res = await dbg.evaluate(expr, frame_id=1, context="watch")

    assert isinstance(res, dict)
    assert "result" in res
    assert "not available" in res["result"]
    assert expr in res["result"]


@pytest.mark.asyncio
async def test_response_handling_resolves_future():
    """Ensure incoming responses resolve the matching pending Future."""
    server = Mock()
    server.send_event = AsyncMock()

    dbg = PyDebugger(server)
    dbg.loop = asyncio.get_running_loop()

    # Prepare pending command future
    command_id = 42
    fut = dbg.loop.create_future()
    dbg._pending_commands = {command_id: fut}

    message = json.dumps({"id": command_id, "body": {"result": "ok"}})

    # Call the message handler (synchronous helper)
    dbg._handle_debug_message(message)

    assert fut.done()
    assert fut.result()["id"] == command_id
    assert command_id not in dbg._pending_commands
