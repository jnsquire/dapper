"""Unit tests for subprocess auto-attach manager."""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import subprocess
import threading
from typing import Any
from typing import cast

from dapper.adapter.subprocess_manager import SubprocessConfig
from dapper.adapter.subprocess_manager import SubprocessManager


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send(self, event: str, payload: dict[str, Any]) -> None:
        self.calls.append((event, payload))


def test_build_launcher_args_rewrites_script_and_program_args() -> None:
    manager = SubprocessManager(
        send_event=lambda _event, _payload: None,
        config=SubprocessConfig(enabled=True, auto_attach=True),
    )

    args = manager.build_launcher_args(["python", "child.py", "--name", "alice"], port=5710)

    assert args[:3] == ["python", "-m", "dapper.launcher.debug_launcher"]
    assert "--program" in args
    program_idx = args.index("--program")
    assert args[program_idx + 1] == "child.py"
    assert args.count("--arg") == 2
    assert args[-2:] == ["--arg", "alice"]


def test_build_launcher_args_rewrites_module_mode() -> None:
    manager = SubprocessManager(
        send_event=lambda _event, _payload: None,
        config=SubprocessConfig(enabled=True, auto_attach=True),
    )

    original = ["python", "-m", "http.server", "8000"]
    args = manager.build_launcher_args(original, port=5710)

    assert args[:3] == ["python", "-m", "dapper.launcher.debug_launcher"]
    assert "--module" in args
    module_idx = args.index("--module")
    assert args[module_idx + 1] == "http.server"
    assert args[-2:] == ["--arg", "8000"]


def test_build_launcher_args_rewrites_code_mode() -> None:
    manager = SubprocessManager(
        send_event=lambda _event, _payload: None,
        config=SubprocessConfig(enabled=True, auto_attach=True),
    )

    original = ["python", "-c", "print('ok')", "arg1"]
    args = manager.build_launcher_args(original, port=5710)

    assert args[:3] == ["python", "-m", "dapper.launcher.debug_launcher"]
    assert "--code" in args
    code_idx = args.index("--code")
    assert args[code_idx + 1] == "print('ok')"
    assert args[-2:] == ["--arg", "arg1"]


def test_enable_patches_and_disable_restores_popen(monkeypatch) -> None:
    recorder = _Recorder()
    manager = SubprocessManager(send_event=recorder.send, config=SubprocessConfig(enabled=True))

    captured: list[Any] = []
    original_init = subprocess.Popen.__init__

    def fake_init(self, args, *rest, **kwargs):
        captured.append(args)
        self.pid = 4321

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)

    manager.enable()
    try:
        subprocess.Popen(["python", "child.py", "--x", "1"])
    finally:
        manager.disable()

    assert captured, "Expected patched Popen to call original __init__"
    rewritten = captured[0]
    assert isinstance(rewritten, list)
    assert "dapper.launcher.debug_launcher" in rewritten
    assert recorder.calls, "Expected child process event to be emitted"
    event_name, payload = recorder.calls[0]
    assert event_name == "dapper/childProcess"
    assert payload["pid"] == 4321
    assert payload["isPython"] is True
    assert isinstance(payload.get("sessionId"), str)

    assert subprocess.Popen.__init__ is fake_init
    monkeypatch.setattr(subprocess.Popen, "__init__", original_init)


def test_non_python_command_passes_through(monkeypatch) -> None:
    manager = SubprocessManager(
        send_event=lambda _event, _payload: None,
        config=SubprocessConfig(enabled=True),
    )

    captured: list[Any] = []

    def fake_init(self, args, *rest, **kwargs):
        captured.append(args)
        self.pid = 100

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)

    manager.enable()
    try:
        subprocess.Popen(["bash", "-lc", "echo hi"])
    finally:
        manager.disable()

    assert captured == [["bash", "-lc", "echo hi"]]


def test_already_instrumented_command_is_not_rewritten(monkeypatch) -> None:
    manager = SubprocessManager(
        send_event=lambda _event, _payload: None,
        config=SubprocessConfig(enabled=True),
    )

    captured: list[Any] = []

    def fake_init(self, args, *rest, **kwargs):
        captured.append(args)
        self.pid = 100

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)

    manager.enable()
    try:
        subprocess.Popen(
            [
                "python",
                "-m",
                "dapper.launcher.debug_launcher",
                "--subprocess",
                "--program",
                "child.py",
            ]
        )
    finally:
        manager.disable()

    assert captured == [
        [
            "python",
            "-m",
            "dapper.launcher.debug_launcher",
            "--subprocess",
            "--program",
            "child.py",
        ]
    ]


def test_emits_child_exited_event(monkeypatch) -> None:
    recorder = _Recorder()
    manager = SubprocessManager(send_event=recorder.send, config=SubprocessConfig(enabled=True))

    exit_wait = threading.Event()

    def fake_init(self, args, *rest, **kwargs):
        self.pid = 2468

        def _wait():
            exit_wait.wait(timeout=1)
            return 0

        self.wait = _wait

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)

    manager.enable()
    try:
        subprocess.Popen(["python", "child.py"])
        exit_wait.set()
        for _ in range(50):
            if any(event == "dapper/childProcessExited" for event, _ in recorder.calls):
                break
            threading.Event().wait(0.01)
    finally:
        manager.disable()

    event_names = [event for event, _ in recorder.calls]
    assert "dapper/childProcess" in event_names
    assert "dapper/childProcessExited" in event_names


def test_session_id_propagates_to_child_args_and_event(monkeypatch) -> None:
    recorder = _Recorder()
    manager = SubprocessManager(
        send_event=recorder.send,
        config=SubprocessConfig(enabled=True, session_id="parent-session-1"),
    )

    captured: list[Any] = []

    def fake_init(self, args, *rest, **kwargs):
        captured.append(args)
        self.pid = 5555

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)

    manager.enable()
    try:
        subprocess.Popen(["python", "child.py"])
    finally:
        manager.disable()

    rewritten = captured[0]
    assert "--session-id" in rewritten
    assert "--parent-session-id" in rewritten
    parent_idx = rewritten.index("--parent-session-id")
    assert rewritten[parent_idx + 1] == "parent-session-1"

    event_name, payload = recorder.calls[0]
    assert event_name == "dapper/childProcess"
    assert payload["parentSessionId"] == "parent-session-1"
    assert isinstance(payload["sessionId"], str)


def test_multiprocessing_scaffold_emits_candidate_event(monkeypatch) -> None:
    recorder = _Recorder()
    manager = SubprocessManager(
        send_event=recorder.send,
        config=SubprocessConfig(enabled=True, enable_multiprocessing_scaffold=True),
    )

    calls: list[str] = []
    original_start = multiprocessing.Process.start

    def fake_start(process_obj, *args, **kwargs):
        del process_obj, args, kwargs
        calls.append("start")

    monkeypatch.setattr(multiprocessing.Process, "start", fake_start)

    manager.enable()
    try:

        class _DummyProc:
            name = "dummy-proc"
            _target = staticmethod(lambda: None)

        multiprocessing.Process.start(cast("Any", _DummyProc()))
    finally:
        manager.disable()
        monkeypatch.setattr(multiprocessing.Process, "start", original_start)

    assert calls == ["start"]
    event_names = [event for event, _ in recorder.calls]
    assert "dapper/childProcessCandidate" in event_names


def test_process_pool_scaffold_emits_candidate_event(monkeypatch) -> None:
    recorder = _Recorder()
    manager = SubprocessManager(
        send_event=recorder.send,
        config=SubprocessConfig(enabled=True, enable_process_pool_scaffold=True),
    )

    calls: list[str] = []
    original_submit = concurrent.futures.ProcessPoolExecutor.submit

    def fake_submit(executor_obj, fn, *args, **kwargs):
        del executor_obj, fn, args, kwargs
        calls.append("submit")
        return "fake-future"

    monkeypatch.setattr(concurrent.futures.ProcessPoolExecutor, "submit", fake_submit)

    manager.enable()
    try:
        concurrent.futures.ProcessPoolExecutor.submit(cast("Any", object()), lambda: None)
    finally:
        manager.disable()
        monkeypatch.setattr(concurrent.futures.ProcessPoolExecutor, "submit", original_submit)

    assert calls == ["submit"]
    event_names = [event for event, _ in recorder.calls]
    assert "dapper/childProcessCandidate" in event_names
