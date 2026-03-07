from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from dapper.launcher import attach_by_pid as mod
from dapper.shared import command_handlers
from dapper.shared.debug_shared import DebugSession


def test_build_remote_exec_script_includes_bootstrap_payload() -> None:
    payload = mod.AttachByPidPayload(
        process_id=123,
        ipc_transport="tcp",
        ipc_host="127.0.0.1",
        ipc_port=9000,
        dapper_root="/tmp/dapper-root",
    )

    script = mod._build_remote_exec_script(payload)

    assert "bootstrap_from_remote_exec" in script
    assert "/tmp/dapper-root" in script
    assert '"processId": 123' in script


def test_attach_by_pid_calls_sys_remote_exec(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[tuple[int, str]] = []

    monkeypatch.setattr(mod, "_resolve_dapper_root", lambda: str(tmp_path))
    monkeypatch.setattr(mod, "_schedule_script_cleanup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mod.sys,
        "remote_exec",
        lambda pid, script_path: calls.append((pid, script_path)),
        raising=False,
    )

    script_path = mod.attach_by_pid(321, ipc_transport="tcp", ipc_port=4567)

    assert calls == [(321, script_path)]
    script_text = Path(script_path).read_text(encoding="utf-8")
    assert "bootstrap_from_remote_exec" in script_text
    Path(script_path).unlink(missing_ok=True)


def test_attach_by_pid_requires_remote_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(mod.sys, "remote_exec", raising=False)

    with pytest.raises(NotImplementedError, match=r"sys\.remote_exec"):
        mod._require_remote_exec()


def test_bootstrap_from_remote_exec_starts_background_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[dict[str, object]] = []

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            started.append({"target": target, "args": args, "daemon": daemon, "name": name})

        def start(self) -> None:
            started.append({"started": True})

    monkeypatch.setattr(mod.threading, "Thread", FakeThread)
    payload_json = json.dumps(
        {
            "processId": 5,
            "ipcTransport": "tcp",
            "ipcHost": "127.0.0.1",
            "ipcPort": 7000,
        }
    )

    mod.bootstrap_from_remote_exec(payload_json)

    assert started[0]["name"] == "dapper-live-attach-bootstrap"
    assert started[1] == {"started": True}


def test_cleanup_attached_session_resets_state(monkeypatch: pytest.MonkeyPatch) -> None:
    session = mod.debug_shared.state
    session.debugger = object()  # type: ignore[assignment]
    session.command_thread = object()  # type: ignore[assignment]
    session.ipc_enabled = True
    session.ipc_sock = object()
    session.ipc_rfile = object()
    session.ipc_wfile = object()
    session.ipc_pipe_conn = object()

    monkeypatch.setattr(mod.sys, "settrace", lambda _fn: None)
    monkeypatch.setattr(mod.threading, "settrace", lambda _fn: None)
    monkeypatch.setattr(mod, "_clear_frame_traces", lambda: None)

    mod._cleanup_attached_session()

    assert session.debugger is None
    assert session.command_thread is None
    assert session.ipc_enabled is False
    assert session.ipc_sock is None


def test_attach_command_acknowledges_and_emits_process_event(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    session = DebugSession()
    session.transport.send = lambda message_type, **payload: sent.append((message_type, payload))  # type: ignore[assignment]
    monkeypatch.setattr(command_handlers, "_active_session", lambda: session)
    monkeypatch.setattr(sys, "argv", ["/tmp/live_app.py"])

    command_handlers._cmd_attach({})

    assert sent[0][0] == "response"
    assert sent[0][1]["success"] is True
    assert sent[1][0] == "process"
    assert sent[1][1]["startMethod"] == "attach"