import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.server import PyDebugger


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

    expected_response = {
        "id": 1,
        "body": {"result": "42", "type": "int", "variablesReference": 0},
    }

    dbg._send_command_to_debuggee = AsyncMock(return_value=expected_response)

    res = await dbg.evaluate("x + 1", frame_id=1, context="watch")
    assert res == expected_response["body"]


@pytest.mark.asyncio
async def test_evaluate_without_response():
    """evaluate() should fall back gracefully when debuggee doesn't respond"""
    server = Mock()
    server.send_event = AsyncMock()

    dbg = PyDebugger(server)
    dbg.loop = asyncio.get_running_loop()
    dbg.process = Mock()
    dbg.is_terminated = False

    dbg._send_command_to_debuggee = AsyncMock(return_value=None)

    expr = "x + 1"
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