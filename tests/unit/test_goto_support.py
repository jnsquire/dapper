from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.shared import command_handlers
from dapper.shared import debug_shared


def test_cmd_goto_targets_returns_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    session = debug_shared.get_active_session()
    dbg = MagicMock()
    dbg.goto_targets.return_value = [{"id": 9, "label": "Line 9", "line": 9}]
    session.debugger = dbg

    result = command_handlers._cmd_goto_targets({"frameId": 3, "line": 9})

    assert result["success"] is True
    assert result["body"]["targets"][0]["id"] == 9
    dbg.goto_targets.assert_called_once_with(3, 9)


def test_cmd_goto_calls_debugger(monkeypatch: pytest.MonkeyPatch) -> None:
    session = debug_shared.get_active_session()
    dbg = MagicMock()
    session.debugger = dbg

    result = command_handlers._cmd_goto({"threadId": 1, "targetId": 21})

    assert result["success"] is True
    dbg.goto.assert_called_once_with(1, 21)


@pytest.mark.asyncio
async def test_external_backend_dispatch_goto_targets_shape() -> None:
    backend = ExternalProcessBackend.__new__(ExternalProcessBackend)
    backend._send_command = AsyncMock(return_value={"body": {"targets": [{"id": 12}]}})

    result = await backend._dispatch_goto_targets({"frame_id": 7, "line": 12})

    cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
    assert cmd["command"] == "gotoTargets"
    assert cmd["arguments"]["frameId"] == 7
    assert cmd["arguments"]["line"] == 12
    assert result == {"targets": [{"id": 12}]}


@pytest.mark.asyncio
async def test_external_backend_dispatch_goto_raises_on_failure() -> None:
    backend = ExternalProcessBackend.__new__(ExternalProcessBackend)
    backend._send_command = AsyncMock(return_value={"success": False, "message": "bad jump"})

    with pytest.raises(ValueError, match="bad jump"):
        await backend._dispatch_goto({"thread_id": 3, "target_id": 18})
