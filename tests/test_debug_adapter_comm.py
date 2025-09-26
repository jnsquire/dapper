import io
import json
import sys

from dapper import debug_adapter_comm as dac


class DummyLock:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return None


def test_dap_mapping_provider_handle_variants():
    # callable returning success dict
    def ok_handler(_args):
        return {"success": True, "body": {}}

    mapping = {"ok": ok_handler}
    p = dac.DapMappingProvider(mapping)
    assert p.supported_commands() == {"ok"}
    assert p.can_handle("ok")
    res = p.handle(None, "ok", {}, None)
    assert isinstance(res, dict)
    assert res.get("success") is True

    # callable returning None (no response)
    def noreply_handler(_args):
        return None

    mapping = {"noreply": noreply_handler}
    p = dac.DapMappingProvider(mapping)
    assert p.handle(None, "noreply", {}, None) is None

    # non-callable mapping entry
    mapping = {"bad": 123}
    p = dac.DapMappingProvider(mapping)
    out = p.handle(None, "bad", {}, None)
    assert isinstance(out, dict)
    assert out.get("success") is False


def test_receive_debug_commands_ipc(monkeypatch):
    # prepare fake state
    s = dac.state
    s.is_terminated = False
    s.ipc_enabled = True
    s.command_queue = []

    # fake reader that returns a DBGCMD line once
    cmd = {"command": "dummy", "seq": 1}
    line = "DBGCMD:" + json.dumps(cmd) + "\n"

    # use StringIO which implements TextIOBase for typing compatibility
    s.ipc_rfile = io.StringIO(line)

    called = []

    def fake_dispatch(c):
        called.append(c)
        # ensure the receive loop exits after first command
        s.is_terminated = True

    class DummyLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(s, "command_lock", DummyLock())
    monkeypatch.setattr(s, "dispatch_debug_command", fake_dispatch)

    # run receiver (should process one command and return)
    dac.receive_debug_commands()
    assert called
    assert called[0]["command"] == "dummy"
    assert s.command_queue
    assert s.command_queue[0]["command"] == "dummy"


def test_process_queued_commands(monkeypatch):
    s = dac.state
    s.command_queue = [{"command": "a"}, {"command": "b"}]

    called = []

    def fake_dispatch(c):
        called.append(c)

    monkeypatch.setattr(s, "command_lock", DummyLock())
    monkeypatch.setattr(s, "dispatch_debug_command", fake_dispatch)

    dac.process_queued_commands()
    assert len(called) == 2
    assert s.command_queue == []


def test_receive_debug_commands_stdin_fallback(monkeypatch):
    s = dac.state
    s.is_terminated = False
    s.ipc_enabled = False
    s.ipc_rfile = None
    s.command_queue = []

    cmd = {"command": "stdin_cmd", "seq": 9}
    line = "DBGCMD:" + json.dumps(cmd) + "\n"

    # patch sys.stdin to a StringIO
    monkeypatch.setattr(sys, "stdin", io.StringIO(line))

    called = []

    def fake_dispatch(c):
        called.append(c)
        s.is_terminated = True

    monkeypatch.setattr(s, "command_lock", DummyLock())
    monkeypatch.setattr(s, "dispatch_debug_command", fake_dispatch)

    dac.receive_debug_commands()

    assert called
    assert called[0]["command"] == "stdin_cmd"
    assert s.command_queue
    assert s.command_queue[0]["command"] == "stdin_cmd"


def test_receive_debug_commands_malformed_json_ipc(monkeypatch):
    s = dac.state
    s.is_terminated = False
    s.ipc_enabled = True
    s.command_queue = []

    # malformed JSON after DBGCMD:
    line = "DBGCMD:{ not-a-json }\n"
    s.ipc_rfile = io.StringIO(line)

    called = []

    def fake_send(event_type, **kwargs):
        # capture the error message and stop the loop
        called.append((event_type, kwargs))
        s.is_terminated = True

    # ensure command_lock exists to satisfy context manager usage if reached
    monkeypatch.setattr(s, "command_lock", DummyLock())
    # patch the module-level send_debug_message used in receive_debug_commands
    monkeypatch.setattr(dac, "send_debug_message", fake_send)

    dac.receive_debug_commands()

    assert called, "send_debug_message was not called for malformed JSON"
    ev, kw = called[0]
    assert ev == "error"
    assert "Error receiving command" in kw.get("message", "")
