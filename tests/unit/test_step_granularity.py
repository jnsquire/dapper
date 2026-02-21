"""Tests for DAP stepGranularity support throughout the adapter stack."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.request_handlers import RequestHandler
from dapper.core.stepping_controller import StepGranularity
from dapper.core.stepping_controller import SteppingController
from dapper.protocol.protocol import ProtocolFactory

# ---------------------------------------------------------------------------
# SteppingController helpers
# ---------------------------------------------------------------------------


class TestStepGranularityHelpers:
    """set_granularity accepts both enums and raw strings."""

    def test_set_from_dap_string_line(self):
        c = SteppingController()
        c.set_granularity("line")
        assert c.granularity is StepGranularity.LINE

    def test_set_from_dap_string_statement(self):
        c = SteppingController()
        c.set_granularity("statement")
        assert c.granularity is StepGranularity.STATEMENT

    def test_set_from_dap_string_instruction(self):
        c = SteppingController()
        c.set_granularity("instruction")
        assert c.granularity is StepGranularity.INSTRUCTION

    def test_none_treated_as_line(self):
        c = SteppingController()
        c.set_granularity("instruction")
        # Simulate client omitting the field (None → "line" after `or "line"`)
        c.set_granularity("line")
        assert c.granularity is StepGranularity.LINE


# ---------------------------------------------------------------------------
# RequestHandler passes granularity to debugger
# ---------------------------------------------------------------------------


class TestRequestHandlerGranularity:
    """_handle_next/_handle_step_in/_handle_step_out forward granularity."""

    def _make_handler(self):
        server = MagicMock()
        server.debugger = MagicMock()
        server.debugger.next = AsyncMock()
        server.debugger.step_in = AsyncMock()
        server.debugger.step_out = AsyncMock()
        handler = RequestHandler(server)
        return handler, server.debugger

    def _make_request(self, command: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "seq": 1,
            "type": "request",
            "command": command,
            "arguments": arguments,
        }

    @pytest.mark.asyncio
    async def test_next_default_granularity(self):
        handler, debugger = self._make_handler()
        request = self._make_request("next", {"threadId": 1})
        await handler._handle_next(request)  # type: ignore[arg-type]
        debugger.next.assert_called_once_with(1, granularity="line")

    @pytest.mark.asyncio
    async def test_next_instruction_granularity(self):
        handler, debugger = self._make_handler()
        request = self._make_request("next", {"threadId": 1, "granularity": "instruction"})
        await handler._handle_next(request)  # type: ignore[arg-type]
        debugger.next.assert_called_once_with(1, granularity="instruction")

    @pytest.mark.asyncio
    async def test_step_in_statement_granularity(self):
        handler, debugger = self._make_handler()
        request = self._make_request("stepIn", {"threadId": 2, "granularity": "statement"})
        await handler._handle_step_in(request)  # type: ignore[arg-type]
        debugger.step_in.assert_called_once_with(2, None, granularity="statement")

    @pytest.mark.asyncio
    async def test_step_out_instruction_granularity(self):
        handler, debugger = self._make_handler()
        request = self._make_request("stepOut", {"threadId": 3, "granularity": "instruction"})
        await handler._handle_step_out(request)  # type: ignore[arg-type]
        debugger.step_out.assert_called_once_with(3, granularity="instruction")


# ---------------------------------------------------------------------------
# ExternalProcessBackend includes granularity in forwarded DAP commands
# ---------------------------------------------------------------------------


class TestExternalBackendGranularity:
    """_dispatch_next/_dispatch_step_in/_dispatch_step_out include granularity."""

    def _make_backend(self):
        backend = ExternalProcessBackend.__new__(ExternalProcessBackend)
        backend._send_command = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_next_line_granularity_omitted(self):
        backend = self._make_backend()
        await backend._dispatch_next({"thread_id": 1, "granularity": "line"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert "granularity" not in cmd["arguments"]

    @pytest.mark.asyncio
    async def test_next_instruction_granularity_included(self):
        backend = self._make_backend()
        await backend._dispatch_next({"thread_id": 1, "granularity": "instruction"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["granularity"] == "instruction"

    @pytest.mark.asyncio
    async def test_step_in_statement_granularity_included(self):
        backend = self._make_backend()
        await backend._dispatch_step_in({"thread_id": 2, "granularity": "statement"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["granularity"] == "statement"

    @pytest.mark.asyncio
    async def test_step_out_instruction_granularity_included(self):
        backend = self._make_backend()
        await backend._dispatch_step_out({"thread_id": 3, "granularity": "instruction"})
        cmd = backend._send_command.call_args[0][0]  # type: ignore[union-attr]
        assert cmd["arguments"]["granularity"] == "instruction"


# ---------------------------------------------------------------------------
# ProtocolFactory creates step requests with granularity
# ---------------------------------------------------------------------------


class TestProtocolFactoryStepRequests:
    """create_next/step_in/step_out_request include granularity when non-default."""

    def _factory(self):
        return ProtocolFactory()

    def test_next_default_no_granularity_key(self):
        req = self._factory().create_next_request(1)
        assert "granularity" not in req["arguments"]

    def test_next_instruction_includes_key(self):
        req = self._factory().create_next_request(1, granularity="instruction")
        assert req["arguments"]["granularity"] == "instruction"

    def test_step_in_default_no_granularity_key(self):
        req = self._factory().create_step_in_request(1)
        assert "granularity" not in req["arguments"]

    def test_step_in_statement_includes_key(self):
        req = self._factory().create_step_in_request(1, granularity="statement")
        assert req["arguments"]["granularity"] == "statement"

    def test_step_in_with_target_id(self):
        req = self._factory().create_step_in_request(1, target_id=42, granularity="line")
        assert req["arguments"]["targetId"] == 42
        assert "granularity" not in req["arguments"]

    def test_step_out_instruction(self):
        req = self._factory().create_step_out_request(5, granularity="instruction")
        assert req["arguments"]["granularity"] == "instruction"
        assert req["arguments"]["threadId"] == 5
