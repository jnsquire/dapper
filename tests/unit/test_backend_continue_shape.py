from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend


class _FakeBridge:
    def __init__(self, result):
        self._result = result

    def continue_(self, _thread_id: int):
        return self._result


@pytest.mark.asyncio
async def test_external_backend_continue_normalizes_from_response_body():
    backend = ExternalProcessBackend(
        ipc=MagicMock(),
        loop=asyncio.get_event_loop(),
        get_process_state=lambda: (MagicMock(), False),
        pending_commands={},
        lock=MagicMock(),
        get_next_command_id=MagicMock(return_value=1),
    )

    async def fake_send(_command, expect_response=False):
        assert expect_response is True
        return {"body": {"allThreadsContinued": False}}

    backend._send_command = fake_send  # type: ignore[assignment]

    result = await backend.continue_(1)
    assert result == {"allThreadsContinued": False}


@pytest.mark.asyncio
async def test_external_backend_continue_defaults_when_body_missing_key():
    backend = ExternalProcessBackend(
        ipc=MagicMock(),
        loop=asyncio.get_event_loop(),
        get_process_state=lambda: (MagicMock(), False),
        pending_commands={},
        lock=MagicMock(),
        get_next_command_id=MagicMock(return_value=1),
    )

    async def fake_send(_command, expect_response=False):
        assert expect_response is True
        return {"body": {"unexpected": 1}}

    backend._send_command = fake_send  # type: ignore[assignment]

    result = await backend.continue_(1)
    assert result == {"allThreadsContinued": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bridge_result", "expected"),
    [
        ({"allThreadsContinued": True}, {"allThreadsContinued": True}),
        ({"unexpected": 1}, {"allThreadsContinued": True}),
        (False, {"allThreadsContinued": False}),
    ],
)
async def test_inprocess_backend_continue_normalizes_bridge_payload(bridge_result, expected):
    backend = InProcessBackend(_FakeBridge(bridge_result))
    result = await backend.continue_(1)
    assert result == expected
