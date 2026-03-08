"""Tests for the low-level eval-frame hook lifecycle controller."""

import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import MagicMock
from unittest.mock import patch

from dapper._frame_eval import get_eval_frame_hook_status
from dapper._frame_eval import install_eval_frame_hook
from dapper._frame_eval import types as frame_types
from dapper._frame_eval import uninstall_eval_frame_hook
from dapper._frame_eval._frame_evaluator import _clear_thread_trace_func
from dapper._frame_eval._frame_evaluator import _collect_code_lines
from dapper._frame_eval._frame_evaluator import _dispatch_eval_frame_entry_trace
from dapper._frame_eval._frame_evaluator import _dispatch_eval_frame_return_trace
from dapper._frame_eval._frame_evaluator import _dispatch_trace_callback
from dapper._frame_eval._frame_evaluator import _get_current_eval_frame_address
from dapper._frame_eval._frame_evaluator import _set_thread_trace_func
from dapper._frame_eval._frame_evaluator import _should_trace_code_for_eval_frame
from dapper._frame_eval._frame_evaluator import _should_trace_code_for_eval_frame_with_frame
from dapper._frame_eval._frame_evaluator import _state
from dapper._frame_eval.cache_manager import invalidate_breakpoints
from dapper._frame_eval.cache_manager import set_breakpoints
from dapper._frame_eval.eval_frame_backend import EvalFrameBackend
from dapper._frame_eval.selective_tracer import get_trace_manager
from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry
from dapper.core.debugger_bdb import DebuggerBDB
from tests.mocks import make_real_frame


def _diff_stats(before: dict[str, object], after: dict[str, object]) -> dict[str, int]:
    keys = (
        "slow_path_attempts",
        "slow_path_activations",
        "scoped_trace_installs",
        "return_events",
        "exception_events",
    )
    result: dict[str, int] = {}
    for key in keys:
        before_value = before.get(key, 0)
        after_value = after.get(key, 0)
        result[key] = int(before_value if isinstance(before_value, int | bool) else 0) - 0
        result[key] = int(after_value if isinstance(after_value, int | bool) else 0) - int(
            before_value if isinstance(before_value, int | bool) else 0
        )
    return result


def test_low_level_hook_install_uninstall_is_idempotent() -> None:
    uninstall_eval_frame_hook()

    assert install_eval_frame_hook() is True
    assert install_eval_frame_hook() is True

    status = get_eval_frame_hook_status()
    assert status["available"] is True
    assert status["installed"] is True

    assert uninstall_eval_frame_hook() is True
    assert uninstall_eval_frame_hook() is True

    status = get_eval_frame_hook_status()
    assert status["available"] is True
    assert status["installed"] is False


def test_types_surface_exposes_hook_status() -> None:
    uninstall_eval_frame_hook()
    assert frame_types.install_eval_frame_hook() is True

    stats = frame_types.get_frame_eval_stats()
    hook_status = frame_types.get_eval_frame_hook_status()

    assert stats["hook_available"] is True
    assert stats["hook_installed"] is True
    assert hook_status["installed"] is True

    assert frame_types.uninstall_eval_frame_hook() is True


def test_eval_frame_pointer_changes_during_install() -> None:
    """Installing/uninstalling should modify the interpreter eval_frame pointer."""
    # ensure fresh start
    uninstall_eval_frame_hook()
    before = _get_current_eval_frame_address()

    assert install_eval_frame_hook() is True
    during = _get_current_eval_frame_address()
    assert during != 0
    # pointer should change from original value (most likely non-zero)
    assert during != before

    assert uninstall_eval_frame_hook() is True
    after = _get_current_eval_frame_address()
    # after uninstall we should restore to original
    assert after == before


def test_eval_frame_decision_matches_breakpointed_line() -> None:
    def sample_function():
        first = 1
        second = 2
        return first + second

    code = sample_function.__code__
    executable_lines = sorted(_collect_code_lines(code))
    breakpoint_line = next(line for line in executable_lines if line > code.co_firstlineno)
    non_breakpoint_line = code.co_firstlineno

    set_breakpoints(code.co_filename, {breakpoint_line})
    try:
        assert _should_trace_code_for_eval_frame(code, breakpoint_line) is True
        assert _should_trace_code_for_eval_frame(code, non_breakpoint_line) is False
    finally:
        invalidate_breakpoints(code.co_filename)


def test_eval_frame_decision_respects_thread_skip_flags() -> None:
    def sample_function():
        return 1

    code = sample_function.__code__
    executable_lines = sorted(_collect_code_lines(code))
    breakpoint_line = next(line for line in executable_lines if line > code.co_firstlineno)
    info = _state.get_thread_info()

    set_breakpoints(code.co_filename, {breakpoint_line})
    try:
        info.is_debugger_internal_thread = True
        assert _should_trace_code_for_eval_frame(code, breakpoint_line) is False

        info.is_debugger_internal_thread = False
        info.skip_all_frames = True
        assert _should_trace_code_for_eval_frame(code, breakpoint_line) is False

        info.skip_all_frames = False
        info.inside_frame_eval = 1
        assert _should_trace_code_for_eval_frame(code, breakpoint_line) is False
    finally:
        info.is_debugger_internal_thread = False
        info.skip_all_frames = False
        info.inside_frame_eval = 0
        invalidate_breakpoints(code.co_filename)


def test_eval_frame_decision_reuses_conditional_breakpoint_logic_when_frame_exists() -> None:
    filename = "/tmp/eval_frame_conditional.py"
    trace_manager = get_trace_manager()
    frame_hit = make_real_frame({"value": 42}, filename=filename, lineno=12, func_name="frame_hit")
    frame_miss = make_real_frame(
        {"value": 0}, filename=filename, lineno=12, func_name="frame_miss"
    )

    trace_manager.set_conditional_breakpoints(
        filename,
        [{"lineno": 12, "condition": "value == 42"}],
    )
    try:
        assert (
            _should_trace_code_for_eval_frame_with_frame(
                frame_hit.f_code,
                frame_hit.f_lineno,
                frame_hit,
            )
            is True
        )
        assert (
            _should_trace_code_for_eval_frame_with_frame(
                frame_miss.f_code,
                frame_miss.f_lineno,
                frame_miss,
            )
            is False
        )
    finally:
        trace_manager.invalidate_file_cache(filename)


def test_eval_frame_decision_conservatively_traces_conditional_breakpoints_without_frame() -> None:
    filename = "/tmp/eval_frame_conditional_pending.py"
    trace_manager = get_trace_manager()
    frame = make_real_frame({"value": 0}, filename=filename, lineno=18, func_name="frame_pending")

    trace_manager.set_conditional_breakpoints(
        filename,
        [{"lineno": 18, "condition": "value == 42"}],
    )
    try:
        assert _should_trace_code_for_eval_frame(frame.f_code, frame.f_lineno) is True
    finally:
        trace_manager.invalidate_file_cache(filename)


def test_eval_frame_decision_traces_when_conditional_breakpoint_falls_back(monkeypatch) -> None:
    """Condition-evaluator fallback should conservatively keep eval-frame on the traced path."""
    filename = "/tmp/eval_frame_conditional_fallback.py"
    trace_manager = get_trace_manager()
    frame = make_real_frame({"value": 0}, filename=filename, lineno=21, func_name="frame_fallback")

    trace_manager.set_conditional_breakpoints(
        filename,
        [{"lineno": 21, "condition": "value == 42"}],
    )

    class _FallbackResult(dict):
        def __init__(self):
            super().__init__(passed=True, fallback=True, error="boom", elapsed_s=0.0)

    class _FallbackEvaluator:
        @staticmethod
        def evaluate(_condition, _frame):
            return _FallbackResult()

    monkeypatch.setattr(
        "dapper._frame_eval.selective_tracer.get_condition_evaluator",
        _FallbackEvaluator,
    )
    try:
        assert (
            _should_trace_code_for_eval_frame_with_frame(
                frame.f_code,
                frame.f_lineno,
                frame,
            )
            is True
        )
    finally:
        trace_manager.invalidate_file_cache(filename)


def test_lazy_instrumentation_triggers_bytecode_injection(monkeypatch) -> None:
    """The eval-frame decision path should lazily call the bytecode injector."""

    # set up a simple function and determine a breakpoint line
    def sample():
        a = 1  # breakpoint
        return a

    code = sample.__code__
    lineno = code.co_firstlineno + 1

    # clear any existing metadata
    from dapper._frame_eval._frame_evaluator import _clear_code_extra_metadata

    _clear_code_extra_metadata(code)

    # monkeypatch the public injector helper
    calls = {"count": 0}

    def fake_inject(co, lines):
        calls["count"] += 1
        return True, co

    monkeypatch.setattr(
        "dapper._frame_eval.modify_bytecode.inject_breakpoint_bytecode",
        fake_inject,
    )

    from dapper._frame_eval.cache_manager import set_breakpoints

    set_breakpoints(code.co_filename, {lineno})
    try:
        result = _should_trace_code_for_eval_frame(code, lineno)
        assert result is True
        assert calls["count"] == 1
    finally:
        set_breakpoints(code.co_filename, set())


def test_lazy_instrumentation_records_modified_code_unavailable(monkeypatch) -> None:
    """A breakpointed frame without generated modified code should emit a distinct reason."""

    def sample():
        a = 1
        return a

    code = sample.__code__
    lineno = next(line for line in _collect_code_lines(code) if line > code.co_firstlineno)

    reset_frame_eval_telemetry()

    def fake_inject(co, lines):
        return True, co

    monkeypatch.setattr(
        "dapper._frame_eval.modify_bytecode.inject_breakpoint_bytecode",
        fake_inject,
    )

    set_breakpoints(code.co_filename, {lineno})
    try:
        assert _should_trace_code_for_eval_frame(code, lineno) is True
        snap = get_frame_eval_telemetry()
        assert snap.reason_counts.modified_code_unavailable == 1
        assert snap.recent_events[-1].reason_code == "MODIFIED_CODE_UNAVAILABLE"
    finally:
        set_breakpoints(code.co_filename, set())


def test_dispatch_trace_callback_uses_registered_callback() -> None:
    calls = []

    def trace_func(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg))

    frame = inspect.currentframe()
    assert frame is not None

    try:
        _set_thread_trace_func(trace_func)
        assert _dispatch_trace_callback(frame, "line", None) is True
        assert calls == [("test_dispatch_trace_callback_uses_registered_callback", "line", None)]
        assert _state.get_thread_info().thread_trace_func is trace_func
        assert frame.f_trace is None
    finally:
        _clear_thread_trace_func()


def test_dispatch_trace_callback_marks_debugger_internal_during_callback() -> None:
    """Nested eval-frame decisions inside debugger callbacks should see debugger-internal state."""

    def sample_function():
        first = 1
        second = 2
        return first + second

    code = sample_function.__code__
    breakpoint_line = next(
        line for line in _collect_code_lines(code) if line > code.co_firstlineno
    )
    decisions: list[bool] = []

    def trace_func(frame, event, arg):
        del frame, event, arg
        decisions.append(_should_trace_code_for_eval_frame(code, breakpoint_line))

    frame = inspect.currentframe()
    assert frame is not None

    set_breakpoints(code.co_filename, {breakpoint_line})
    try:
        _set_thread_trace_func(trace_func)
        assert _dispatch_trace_callback(frame, "line", None) is True
        assert decisions == [False]
        assert _state.get_thread_info().is_debugger_internal_thread is False
    finally:
        invalidate_breakpoints(code.co_filename)
        _clear_thread_trace_func()


def test_dispatch_trace_callback_persists_local_frame_trace() -> None:
    calls = []

    def local_trace(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg, "local"))

    def root_trace(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg, "root"))
        return local_trace

    frame = inspect.currentframe()
    assert frame is not None

    try:
        frame.f_trace = None
        _set_thread_trace_func(root_trace)

        assert _dispatch_trace_callback(frame, "line", None) is True
        assert frame.f_trace is local_trace
        assert _state.get_thread_info().thread_trace_func is root_trace

        assert _dispatch_trace_callback(frame, "return", None) is True
        assert frame.f_trace is None
        assert calls == [
            ("test_dispatch_trace_callback_persists_local_frame_trace", "line", None, "root"),
            ("test_dispatch_trace_callback_persists_local_frame_trace", "return", None, "local"),
        ]
    finally:
        frame.f_trace = None
        _clear_thread_trace_func()


def test_eval_frame_entry_and_return_dispatch_use_trace_lifecycle() -> None:
    calls = []
    sentinel = object()

    def local_trace(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg, "local"))
        if event == "return":
            return None
        return local_trace

    def root_trace(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg, "root"))
        return local_trace

    frame = inspect.currentframe()
    assert frame is not None

    try:
        frame.f_trace = None
        _set_thread_trace_func(root_trace)

        assert _dispatch_eval_frame_entry_trace(frame) is True
        assert frame.f_trace is local_trace

        assert _dispatch_eval_frame_return_trace(frame, sentinel) is True
        assert frame.f_trace is None
        assert len(calls) == 3
        assert calls[0] == (
            "test_eval_frame_entry_and_return_dispatch_use_trace_lifecycle",
            "call",
            None,
            "root",
        )
        assert calls[1] == (
            "test_eval_frame_entry_and_return_dispatch_use_trace_lifecycle",
            "line",
            None,
            "local",
        )
        assert calls[2][0] == "test_eval_frame_entry_and_return_dispatch_use_trace_lifecycle"
        assert calls[2][1] == "return"
        assert calls[2][2] is sentinel
        assert calls[2][3] == "local"
    finally:
        frame.f_trace = None
        _clear_thread_trace_func()


def test_eval_frame_entry_respects_trace_opt_out_after_call() -> None:
    calls = []

    def root_trace(frame, event, arg):
        calls.append((frame.f_code.co_name, event, arg))

    frame = inspect.currentframe()
    assert frame is not None

    try:
        frame.f_trace = None
        _set_thread_trace_func(root_trace)

        assert _dispatch_eval_frame_entry_trace(frame) is True
        assert frame.f_trace is None
        assert _dispatch_eval_frame_return_trace(frame, "done") is False
        assert calls == [
            ("test_eval_frame_entry_respects_trace_opt_out_after_call", "call", None),
        ]
    finally:
        frame.f_trace = None
        _clear_thread_trace_func()


def test_live_eval_frame_hook_does_not_crash_or_dispatch_caller_frame() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import json

from dapper._frame_eval import install_eval_frame_hook, uninstall_eval_frame_hook
from dapper._frame_eval import types as frame_types
from dapper._frame_eval.cache_manager import invalidate_breakpoints, set_breakpoints
from dapper._frame_eval._frame_evaluator import _clear_thread_trace_func
from dapper._frame_eval._frame_evaluator import _collect_code_lines
from dapper._frame_eval._frame_evaluator import _set_thread_trace_func

seen = []


def diff_stats(before, after):
    keys = ("slow_path_attempts", "slow_path_activations", "scoped_trace_installs", "return_events", "exception_events")
    return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


def local_trace(frame, event, arg):
    seen.append([frame.f_code.co_name, event, arg])
    if event == "return":
        return None
    return local_trace


def root_trace(frame, event, arg):
    seen.append([frame.f_code.co_name, event, arg])
    return local_trace


def helper_function():
    return 3


def sample_function():
    interim = helper_function()
    marker = {"ok": True, "value": 7 + interim}
    return marker


lines = sorted(_collect_code_lines(sample_function.__code__))
set_breakpoints(sample_function.__code__.co_filename, set(lines))
try:
    _set_thread_trace_func(root_trace)
    installed = install_eval_frame_hook()
    stats_before = frame_types.get_frame_eval_stats()
    result = sample_function()
    stats_after = frame_types.get_frame_eval_stats()
    print(json.dumps({"installed": installed, "result": result, "seen": seen, "stats_delta": diff_stats(stats_before, stats_after)}, sort_keys=True))
finally:
    uninstall_eval_frame_hook()
    _clear_thread_trace_func()
    invalidate_breakpoints(sample_function.__code__.co_filename)
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert stdout_lines, result.stderr

        payload = json.loads(stdout_lines[-1])
        assert payload["installed"] is True
        assert payload["result"] == {"ok": True, "value": 10}
        assert payload["seen"]
        assert all(name == "sample_function" for name, _event, _arg in payload["seen"])
        events = [event for _name, event, _arg in payload["seen"]]
        assert events[0] == "call"
        assert events[-1] == "return"
        assert all(event == "line" for event in events[1:-1])
        assert payload["seen"][-1][2] == {"ok": True, "value": 10}
        assert payload["stats_delta"]["slow_path_attempts"] >= 1
        assert payload["stats_delta"]["slow_path_activations"] >= 1
        assert payload["stats_delta"]["scoped_trace_installs"] >= 1
        assert payload["stats_delta"]["return_events"] >= 1
    finally:
        script_path.unlink(missing_ok=True)


def test_live_eval_frame_hook_propagates_exception_event() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import json

from dapper._frame_eval import install_eval_frame_hook, uninstall_eval_frame_hook
from dapper._frame_eval import types as frame_types
from dapper._frame_eval.cache_manager import invalidate_breakpoints, set_breakpoints
from dapper._frame_eval._frame_evaluator import _clear_thread_trace_func
from dapper._frame_eval._frame_evaluator import _collect_code_lines
from dapper._frame_eval._frame_evaluator import _set_thread_trace_func

seen = []


def diff_stats(before, after):
    keys = ("slow_path_attempts", "slow_path_activations", "scoped_trace_installs", "return_events", "exception_events")
    return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


def encode_arg(event, arg):
    if event == "exception":
        exc_type, exc_value, exc_tb = arg
        return [exc_type.__name__, str(exc_value), exc_tb is not None]
    return arg


def local_trace(frame, event, arg):
    seen.append([frame.f_code.co_name, event, encode_arg(event, arg)])
    if event in ("return", "exception"):
        return None
    return local_trace


def root_trace(frame, event, arg):
    seen.append([frame.f_code.co_name, event, encode_arg(event, arg)])
    return local_trace


def sample_function():
    raise ValueError("boom")


lines = sorted(_collect_code_lines(sample_function.__code__))
set_breakpoints(sample_function.__code__.co_filename, set(lines))
try:
    _set_thread_trace_func(root_trace)
    installed = install_eval_frame_hook()
    stats_before = frame_types.get_frame_eval_stats()
    caught = None
    try:
        sample_function()
    except Exception as exc:
        caught = [type(exc).__name__, str(exc)]
    stats_after = frame_types.get_frame_eval_stats()
    print(json.dumps({"caught": caught, "installed": installed, "seen": seen, "stats_delta": diff_stats(stats_before, stats_after)}, sort_keys=True))
finally:
    uninstall_eval_frame_hook()
    _clear_thread_trace_func()
    invalidate_breakpoints(sample_function.__code__.co_filename)
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert stdout_lines, result.stderr

        payload = json.loads(stdout_lines[-1])
        assert payload["installed"] is True
        assert payload["caught"] == ["ValueError", "boom"]
        assert payload["seen"]
        assert all(name == "sample_function" for name, _event, _arg in payload["seen"])
        events = [event for _name, event, _arg in payload["seen"]]
        assert events[0] == "call"
        assert "exception" in events
        exception_index = events.index("exception")
        assert all(event == "line" for event in events[1:exception_index])
        assert payload["seen"][exception_index][2] == ["ValueError", "boom", True]
        assert payload["stats_delta"]["slow_path_attempts"] >= 1
        assert payload["stats_delta"]["slow_path_activations"] >= 1
        assert payload["stats_delta"]["scoped_trace_installs"] >= 1
        assert payload["stats_delta"]["exception_events"] >= 1
    finally:
        script_path.unlink(missing_ok=True)


def test_eval_frame_backend_install_sets_trace_callback() -> None:
    class DummyDebugger:
        def trace_dispatch(self, _frame, _event, _arg):
            return None

    backend = EvalFrameBackend()
    info = _state.get_thread_info()

    try:
        backend.install(DummyDebugger())
        assert callable(info.thread_trace_func)
        assert backend.get_statistics()["installed"] is True
    finally:
        backend.shutdown()
        _clear_thread_trace_func()

    assert info.thread_trace_func is None


def test_eval_frame_backend_dispatch_reaches_debugger_breakpoint_logic() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write("x = 1\ny = 2\nz = 3\nresult = x + y\nprint(z)\n")
        path = handle.name

    mock_send = MagicMock()
    debugger = DebuggerBDB(send_message=mock_send)
    debugger.reset()
    debugger.process_commands = MagicMock()
    debugger.set_break(path, 4)
    frame = make_real_frame({"x": 1, "y": 2}, filename=path, lineno=4)
    backend = EvalFrameBackend()

    try:
        with (
            patch("dapper._frame_eval.eval_frame_backend.install_eval_frame_hook"),
            patch("dapper._frame_eval.eval_frame_backend.uninstall_eval_frame_hook"),
        ):
            backend.install(debugger)
            assert _dispatch_trace_callback(frame, "line", None) is True

        mock_send.assert_any_call(
            "stopped",
            threadId=threading.get_ident(),
            reason="breakpoint",
            allThreadsStopped=True,
        )
    finally:
        backend.shutdown()
        Path(path).unlink(missing_ok=True)
