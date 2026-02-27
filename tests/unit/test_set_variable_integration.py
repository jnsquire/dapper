"""
Integration test for setVariable functionality.

Verifies that the variable-setting pipeline — DAP request → RequestHandler →
PyDebugger → VariableManager → backend — works end-to-end using a real
``PyDebugger`` and ``RequestHandler`` wired to a mock server.  A mock backend
simulates the actual value conversion so we can confirm that the entire
chain produces a valid DAP response.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.adapter.debugger.py_debugger import PyDebugger
from dapper.adapter.request_handlers import RequestHandler


@pytest.fixture
def wired_handler():
    """Create a real PyDebugger + RequestHandler backed by a mock server.

    The PyDebugger's active backend is a mock that echoes the requested
    value so we can test the full request-handler → set_variable pipeline
    without needing a subprocess.
    """
    server = Mock()
    server.send_event = AsyncMock()
    server.send_message = AsyncMock()
    server.protocol_handler = Mock()

    _seq = 0

    @property
    def _next_seq(self):
        nonlocal _seq
        _seq += 1
        return _seq

    type(server).next_seq = _next_seq

    debugger = PyDebugger(server)
    server.debugger = debugger
    server._debugger = debugger

    handler = RequestHandler(server)

    # Set up a scope reference so set_variable recognizes it
    frame_id = 1
    scope_ref = debugger.variable_manager.allocate_scope_ref(frame_id, "locals")

    # Provide a mock backend that returns sensible responses
    mock_backend = AsyncMock()

    async def _mock_set_variable(var_ref: int, name: str, value: str) -> dict[str, Any]:
        return {"value": value, "type": type(eval(value)).__name__, "variablesReference": 0}

    mock_backend.set_variable = AsyncMock(side_effect=_mock_set_variable)

    # Patch the active-backend getter
    debugger.get_active_backend = Mock(return_value=mock_backend)

    return handler, debugger, scope_ref, mock_backend


@pytest.mark.asyncio
async def test_set_variable_integration(wired_handler):
    """Send three setVariable requests through the full adapter pipeline.

    Verifies that RequestHandler dispatches to PyDebugger.set_variable,
    which resolves the scope reference and delegates to the active backend,
    and that each response is well-formed.
    """
    handler, _debugger, scope_ref, mock_backend = wired_handler

    # --- setVariable: x = 99 ---
    resp_x = await handler.handle_request(
        {
            "seq": 10,
            "type": "request",
            "command": "setVariable",
            "arguments": {
                "variablesReference": scope_ref,
                "name": "x",
                "value": "99",
            },
        }
    )
    assert resp_x["success"], f"setVariable(x) failed: {resp_x.get('message')}"
    assert resp_x["body"]["value"] == "99"

    # --- setVariable: y = 'world' ---
    resp_y = await handler.handle_request(
        {
            "seq": 11,
            "type": "request",
            "command": "setVariable",
            "arguments": {
                "variablesReference": scope_ref,
                "name": "y",
                "value": "'world'",
            },
        }
    )
    assert resp_y["success"], f"setVariable(y) failed: {resp_y.get('message')}"
    assert resp_y["body"]["value"] == "'world'"

    # --- setVariable: z = [9, 8, 7] ---
    resp_z = await handler.handle_request(
        {
            "seq": 12,
            "type": "request",
            "command": "setVariable",
            "arguments": {
                "variablesReference": scope_ref,
                "name": "z",
                "value": "[9, 8, 7]",
            },
        }
    )
    assert resp_z["success"], f"setVariable(z) failed: {resp_z.get('message')}"
    assert resp_z["body"]["value"] == "[9, 8, 7]"

    # Verify the backend received three set_variable calls
    assert mock_backend.set_variable.call_count == 3
    calls = mock_backend.set_variable.call_args_list
    assert calls[0].args == (scope_ref, "x", "99")
    assert calls[1].args == (scope_ref, "y", "'world'")
    assert calls[2].args == (scope_ref, "z", "[9, 8, 7]")
