from __future__ import annotations

from types import SimpleNamespace

import dapper._frame_eval.selective_tracer as st


class _FakeCode:
    def __init__(self, filename: str, name: str = "fn", firstlineno: int = 10):
        self.co_filename = filename
        self.co_name = name
        self.co_firstlineno = firstlineno


class _FakeFrame:
    def __init__(self, filename: str, lineno: int, name: str = "fn", firstlineno: int = 10):
        self.f_code = _FakeCode(filename, name, firstlineno)
        self.f_lineno = lineno


class _FakeThreadInfo:
    def __init__(
        self,
        *,
        skip: bool = False,
        fully_initialized: bool = True,
        step_mode: bool = False,
    ):
        self._skip = skip
        self.fully_initialized = fully_initialized
        self.step_mode = step_mode

    def should_skip_frame(self, _filename: str) -> bool:
        return self._skip


def test_analyzer_should_track_file_patterns():
    analyzer = st.FrameTraceAnalyzer()
    assert analyzer._should_track_file("/workspace/app.py") is True
    assert analyzer._should_track_file("<generated>") is False
    assert analyzer._should_track_file("/usr/lib/python/site-packages/pkg/x.py") is False
    assert analyzer._should_track_file("/workspace/app.txt") is False


def test_should_trace_frame_skips_when_thread_requests(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    frame = _FakeFrame("/workspace/app.py", lineno=20)

    monkeypatch.setattr(st, "get_thread_info", lambda: _FakeThreadInfo(skip=True))
    decision = analyzer.should_trace_frame(frame)

    assert decision["should_trace"] is False
    assert decision["reason"] == "thread_skip_frame"


def test_should_trace_frame_breakpoint_on_current_line(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    frame = _FakeFrame("/workspace/app.py", lineno=12)

    monkeypatch.setattr(st, "get_thread_info", lambda: _FakeThreadInfo(skip=False))
    monkeypatch.setattr(st, "get_breakpoints", lambda _filename: {12, 15})

    decision = analyzer.should_trace_frame(frame)

    assert decision["should_trace"] is True
    assert decision["reason"] == "breakpoint_on_line"
    assert decision["breakpoint_lines"] == {12}


def test_should_trace_frame_function_breakpoints_in_step_mode(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    frame = _FakeFrame("/workspace/app.py", lineno=30, firstlineno=10)

    monkeypatch.setattr(st, "get_thread_info", lambda: _FakeThreadInfo(step_mode=True))
    monkeypatch.setattr(st, "get_breakpoints", lambda _filename: {28, 40, 99})
    monkeypatch.setattr(analyzer, "_estimate_function_end", lambda _frame: 40)

    decision = analyzer.should_trace_frame(frame)

    assert decision["should_trace"] is True
    assert decision["reason"] == "function_has_breakpoints"
    assert decision["breakpoint_lines"] == {28, 40}


def test_should_trace_frame_with_untracked_file_and_no_breakpoints(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    frame = _FakeFrame("<generated>", lineno=1)

    monkeypatch.setattr(st, "get_thread_info", _FakeThreadInfo)
    monkeypatch.setattr(st, "get_breakpoints", lambda _filename: set())

    decision = analyzer.should_trace_frame(frame)

    assert decision["should_trace"] is False
    assert decision["reason"] == "file_not_tracked"


def test_estimate_function_end_fallback_when_disassembly_fails(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    frame = _FakeFrame("/workspace/app.py", lineno=10, firstlineno=25)

    def explode(_code):
        msg = "broken disassembly"
        raise RuntimeError(msg)

    monkeypatch.setattr(st.dis, "get_instructions", explode)
    assert analyzer._estimate_function_end(frame) == 125


def test_analyzer_update_and_invalidate_clear_cached_keys(monkeypatch):
    analyzer = st.FrameTraceAnalyzer()
    analyzer._analysis_cache = {
        "/workspace/app.py:1": "x",
        "/workspace/app.py:2": "y",
        "/workspace/other.py:1": "z",
    }

    calls: list[tuple[str, str, object]] = []

    def fake_set(filename, breakpoints):
        calls.append(("set", filename, tuple(breakpoints)))

    def fake_invalidate(filename):
        calls.append(("invalidate", filename, None))

    monkeypatch.setattr(st, "set_breakpoints", fake_set)
    monkeypatch.setattr(st, "invalidate_breakpoints", fake_invalidate)

    analyzer.update_breakpoints("/workspace/app.py", [1, 2, 3])
    assert "/workspace/other.py:1" in analyzer._analysis_cache
    assert "/workspace/app.py:1" not in analyzer._analysis_cache

    analyzer._analysis_cache["/workspace/app.py:9"] = "again"
    analyzer.invalidate_file("/workspace/app.py")
    assert "/workspace/app.py:9" not in analyzer._analysis_cache
    assert calls[0][0] == "set"
    assert calls[1][0] == "invalidate"


def test_dispatcher_stats_for_none_frame_and_skip(monkeypatch):
    dispatcher = st.SelectiveTraceDispatcher(lambda *_args, **_kwargs: "trace")

    assert dispatcher.selective_trace_dispatch(None, "line", None) is None

    frame = _FakeFrame("/workspace/app.py", lineno=50)
    monkeypatch.setattr(
        dispatcher.analyzer,
        "should_trace_frame",
        lambda _frame: {
            "should_trace": False,
            "reason": "no_breakpoints_in_function",
            "breakpoint_lines": set(),
            "frame_info": {
                "filename": "/workspace/app.py",
                "function": "fn",
                "lineno": 50,
                "is_module": False,
            },
        },
    )

    assert dispatcher.selective_trace_dispatch(frame, "line", None) is None
    stats = dispatcher.get_statistics()["dispatcher_stats"]
    assert stats["total_calls"] == 2
    assert stats["skipped_calls"] == 1


def test_dispatcher_dispatches_when_decision_is_true(monkeypatch):
    called: list[tuple[str, int]] = []

    def trace_func(frame, event, _arg):
        called.append((event, frame.f_lineno))
        return "trace-result"

    dispatcher = st.SelectiveTraceDispatcher(trace_func)
    frame = _FakeFrame("/workspace/app.py", lineno=7)

    monkeypatch.setattr(
        dispatcher.analyzer,
        "should_trace_frame",
        lambda _frame: {
            "should_trace": True,
            "reason": "breakpoint_on_line",
            "breakpoint_lines": {7},
            "frame_info": {
                "filename": "/workspace/app.py",
                "function": "fn",
                "lineno": 7,
                "is_module": False,
            },
        },
    )

    assert dispatcher.selective_trace_dispatch(frame, "line", None) == "trace-result"
    assert called == [("line", 7)]


def test_frame_trace_manager_breakpoint_lifecycle(monkeypatch):
    manager = st.FrameTraceManager()

    updates: list[tuple[str, set[int]]] = []
    invalidates: list[str] = []

    monkeypatch.setattr(
        manager.dispatcher,
        "update_breakpoints",
        lambda filename, bps: updates.append((filename, set(bps))),
    )
    monkeypatch.setattr(
        manager.dispatcher,
        "invalidate_file",
        invalidates.append,
    )

    manager.update_file_breakpoints("/workspace/a.py", {1, 2})
    manager.add_breakpoint("/workspace/a.py", 3)
    manager.remove_breakpoint("/workspace/a.py", 2)

    assert manager.get_breakpoints("/workspace/a.py") == {1, 3}
    assert manager.get_all_breakpoints()["/workspace/a.py"] == {1, 3}

    manager.invalidate_file_cache("/workspace/a.py")
    assert invalidates == ["/workspace/a.py"]

    manager.clear_breakpoints("/workspace/a.py")
    assert manager.get_breakpoints("/workspace/a.py") == set()

    # Ensure dispatcher update hooks were called throughout lifecycle.
    assert any(path == "/workspace/a.py" for path, _ in updates)


def test_global_wrapper_functions_route_to_trace_manager(monkeypatch):
    fake = SimpleNamespace(
        enable_selective_tracing=lambda _fn: "enabled",
        disable_selective_tracing=lambda: "disabled",
        get_trace_function=lambda: "trace-fn",
        update_file_breakpoints=lambda filename, breakpoints: (filename, breakpoints),
        add_breakpoint=lambda filename, lineno: (filename, lineno),
        remove_breakpoint=lambda filename, lineno: (filename, lineno),
        get_statistics=lambda: {"ok": True},
    )
    monkeypatch.setattr(st, "_trace_manager", fake)

    st.enable_selective_tracing(lambda *_args: None)
    st.disable_selective_tracing()
    assert st.get_selective_trace_function() == "trace-fn"
    st.update_breakpoints("/workspace/a.py", {1})
    st.add_breakpoint("/workspace/a.py", 2)
    st.remove_breakpoint("/workspace/a.py", 1)
    assert st.get_tracing_statistics() == {"ok": True}
