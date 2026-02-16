from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dapper.adapter.server import PyDebugger


class _FakeServer:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    async def send_event(self, name: str, body: dict[str, Any] | None = None) -> None:
        self.events.append((name, body))


@pytest.fixture
def debugger() -> PyDebugger:
    loop = asyncio.new_event_loop()
    dbg = PyDebugger(_FakeServer(), loop=loop)
    try:
        yield dbg
    finally:
        if not loop.is_closed():
            loop.close()


@pytest.mark.asyncio
async def _install_wrapper_stubs(debugger: PyDebugger) -> None:
    async def _continue(thread_id: int):
        return {"allThreadsContinued": thread_id == 1}

    async def _next(_thread_id: int):
        return None

    async def _step_in(_thread_id: int, _target_id: int | None = None):
        return None

    async def _step_out(_thread_id: int):
        return None

    async def _pause(_thread_id: int):
        return True

    async def _threads():
        return [{"id": 1, "name": "MainThread"}]

    async def _stack(_thread_id: int, _start: int = 0, _levels: int = 0):
        return {"stackFrames": [], "totalFrames": 0}

    async def _scopes(_frame_id: int):
        return [{"name": "Locals", "variablesReference": 1, "expensive": False}]

    async def _vars(_ref: int, _f: str = "", _s: int = 0, _c: int = 0):
        return [{"name": "x", "value": "1", "variablesReference": 0}]

    async def _set_var(_ref: int, _name: str, _value: str):
        return {"value": "2", "type": "int", "variablesReference": 0}

    async def _evaluate(_expr: str, _frame_id: int | None = None, _ctx: str | None = None):
        return {"result": "ok", "variablesReference": 0}

    async def _exc_info(_thread_id: int):
        return {
            "exceptionId": "ValueError",
            "description": "bad",
            "breakMode": "always",
            "details": {},
        }

    async def _done():
        return None

    async def _disconnect(_terminate_debuggee: bool = False):
        return None

    async def _terminate():
        return None

    async def _restart():
        return None

    async def _send_cmd(_cmd: str):
        return None

    async def _set_breakpoints(_source: Any, _bps: list[dict[str, Any]]):
        return [{"verified": True, "line": 1}]

    debugger._execution_manager.continue_execution = _continue
    debugger._execution_manager.next = _next
    debugger._execution_manager.step_in = _step_in
    debugger._execution_manager.step_out = _step_out
    debugger._execution_manager.pause = _pause
    debugger._execution_manager.get_threads = _threads
    debugger._execution_manager.exception_info = _exc_info
    debugger._execution_manager.configuration_done_request = _done
    debugger._execution_manager.disconnect = _disconnect
    debugger._execution_manager.terminate = _terminate
    debugger._execution_manager.restart = _restart
    debugger._execution_manager.send_command_to_debuggee = _send_cmd

    debugger._state_manager.get_stack_trace = _stack
    debugger._state_manager.get_scopes = _scopes
    debugger._state_manager.get_variables = _vars
    debugger._state_manager.set_variable = _set_var
    debugger._state_manager.evaluate = _evaluate
    debugger._state_manager.set_breakpoints = _set_breakpoints


@pytest.mark.asyncio
async def test_pydebugger_wrapper_delegation_execution_paths(debugger: PyDebugger):
    await _install_wrapper_stubs(debugger)

    assert await debugger.continue_execution(1) == {"allThreadsContinued": True}
    await debugger.next(1)
    await debugger.step_in(1, 123)
    await debugger.step_out(1)
    assert await debugger.pause(1) is True
    assert await debugger.get_threads() == [{"id": 1, "name": "MainThread"}]

    assert (await debugger.exception_info(1))["exceptionId"] == "ValueError"
    assert (await debugger.get_exception_info(1))["exceptionId"] == "ValueError"

    await debugger.configuration_done_request()
    await debugger.disconnect(False)
    await debugger.terminate()
    await debugger.restart()
    await debugger.send_command_to_debuggee("continue")


@pytest.mark.asyncio
async def test_pydebugger_wrapper_delegation_state_paths(debugger: PyDebugger):
    await _install_wrapper_stubs(debugger)

    assert await debugger.get_stack_trace(1, 0, 10) == {"stackFrames": [], "totalFrames": 0}
    assert (await debugger.get_scopes(1))[0]["name"] == "Locals"
    assert (await debugger.get_variables(1))[0]["name"] == "x"
    assert (await debugger.set_variable(1, "x", "2"))["value"] == "2"
    assert (await debugger.evaluate("x", 1, "watch"))["result"] == "ok"
    assert (await debugger.evaluate_expression("x", 1, "hover"))["result"] == "ok"

    assert (await debugger.set_breakpoints("/tmp/a.py", [{"line": 1}]))[0]["verified"] is True


@pytest.mark.asyncio
async def test_pydebugger_handle_program_exit_and_message_aliases(debugger: PyDebugger):
    handled: list[str] = []

    def _capture_message(message: str) -> None:
        handled.append(message)

    debugger._handle_debug_message = _capture_message

    await debugger.handle_debug_message({"event": "stopped"})
    await debugger.handle_debug_message("raw")

    assert handled[0].startswith("{")
    assert handled[1] == "raw"

    debugger.program_running = True
    debugger.is_terminated = False
    await debugger.handle_program_exit(7)

    assert debugger.program_running is False
    assert debugger.is_terminated is True
    server = debugger.server
    assert isinstance(server, _FakeServer)
    assert ("exited", {"exitCode": 7}) in server.events
    assert any(name == "terminated" for name, _ in server.events)


@pytest.mark.asyncio
async def test_data_breakpoint_info_and_set_data_breakpoints(debugger: PyDebugger):
    frame = SimpleNamespace(f_locals={"value": 123})
    debugger.current_frame = frame

    info = debugger.data_breakpoint_info(name="value", frame_id=12)
    assert info["dataId"] == "frame:12:var:value"
    assert info["type"] == "int"
    assert info["value"] == "123"

    result = debugger.set_data_breakpoints(
        [
            {"dataId": "frame:12:var:value", "accessType": "write"},
            {"dataId": None},
        ]
    )
    assert result[0]["verified"] is True
    assert result[1]["verified"] is False


@pytest.mark.asyncio
async def test_set_function_exception_breakpoints_backend_and_fallback(debugger: PyDebugger):
    class _Backend:
        async def set_function_breakpoints(self, breakpoints):
            return [{"verified": True, "name": breakpoints[0]["name"]}]

        async def set_exception_breakpoints(self, filters, _filter_options, _exception_options):
            return [{"verified": bool(filters)}]

        async def completions(self, _text, _column, _frame_id, _line):
            return {"targets": [{"label": "x", "type": "property"}]}

    debugger._external_backend = _Backend()

    fb = await debugger.set_function_breakpoints([{"name": "foo", "condition": "x > 1"}])
    assert fb[0]["verified"] is True

    eb = await debugger.set_exception_breakpoints(["raised"])
    assert eb[0]["verified"] is True

    comp = await debugger.completions("x.", 2, frame_id=1, line=1)
    assert comp["targets"][0]["label"] == "x"

    debugger._external_backend = None
    fallback = await debugger.set_exception_breakpoints(["uncaught"])
    assert fallback == [{"verified": True}]
