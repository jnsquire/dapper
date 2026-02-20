"""Tests for selective frame tracing and conditional breakpoints."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

from dapper._frame_eval.selective_tracer import ConditionalBreakpointSpec
from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
from dapper._frame_eval.selective_tracer import FrameTraceManager

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_frame(filename: str, lineno: int, local_vars: dict | None = None) -> MagicMock:
    """Return a minimal mock frame for a given file/line."""
    frame = MagicMock()
    frame.f_code.co_filename = filename
    frame.f_code.co_name = "test_func"
    frame.f_code.co_firstlineno = 1
    frame.f_lineno = lineno
    frame.f_locals = local_vars or {}
    frame.f_globals = {}
    return frame


@contextmanager
def _with_breakpoints(_filename: str, lines: set[int]):
    """Patch get_breakpoints so the analyzer sees a controlled breakpoint set.

    Using the real global cache is unreliable in a full test suite run because
    other tests call clear_all_caches().  Patching at the module level gives
    deterministic isolation.
    """
    with patch(
        "dapper._frame_eval.selective_tracer.get_breakpoints",
        return_value=lines,
    ):
        yield


# ---------------------------------------------------------------------------
# FrameTraceAnalyzer — unconditional behaviour
# ---------------------------------------------------------------------------


class TestFrameTraceAnalyzerUnconditional:
    def test_no_breakpoints_skips_trace(self):
        analyzer = FrameTraceAnalyzer()
        frame = _make_frame("/src/mymodule.py", 5)
        with patch("dapper._frame_eval.selective_tracer.get_breakpoints", return_value=None):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is False

    def test_matching_breakpoint_traces_frame(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/module_bp.py"
        frame = _make_frame(filename, 10)
        with _with_breakpoints(filename, {10}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is True
        assert decision["reason"] == "breakpoint_on_line"

    def test_non_matching_line_skips_trace(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/module_nonmatch.py"
        frame = _make_frame(filename, 99)
        with _with_breakpoints(filename, {10}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is False


# ---------------------------------------------------------------------------
# FrameTraceAnalyzer — conditional breakpoints fast-path
# ---------------------------------------------------------------------------


class TestFrameTraceAnalyzerConditional:
    def test_true_condition_allows_trace(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_true.py"
        analyzer.set_breakpoint_conditions(filename, {5: "True"})
        frame = _make_frame(filename, 5, local_vars={"x": 10})
        with _with_breakpoints(filename, {5}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is True

    def test_false_condition_skips_trace(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_false.py"
        analyzer.set_breakpoint_conditions(filename, {5: "False"})
        frame = _make_frame(filename, 5)
        with _with_breakpoints(filename, {5}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is False
        assert decision["reason"] == "condition_not_met"

    def test_condition_uses_frame_locals(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_locals.py"
        analyzer.set_breakpoint_conditions(filename, {20: "value == 42"})

        frame_hit = _make_frame(filename, 20, local_vars={"value": 42})
        frame_miss = _make_frame(filename, 20, local_vars={"value": 0})

        with _with_breakpoints(filename, {20}):
            assert analyzer.should_trace_frame(frame_hit)["should_trace"] is True
            assert analyzer.should_trace_frame(frame_miss)["should_trace"] is False

    def test_condition_error_falls_back_to_trace(self):
        """A broken condition expression is conservative: trace the frame."""
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_error.py"
        analyzer.set_breakpoint_conditions(filename, {7: "undefined_name > 0"})
        frame = _make_frame(filename, 7, local_vars={})
        with _with_breakpoints(filename, {7}):
            decision = analyzer.should_trace_frame(frame)
        # fallback=True → passed=True → should_trace=True
        assert decision["should_trace"] is True

    def test_none_condition_treated_as_unconditional(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_none.py"
        # Passing None condition should store no entry (unconditional)
        analyzer.set_breakpoint_conditions(filename, {3: None})
        frame = _make_frame(filename, 3)
        with _with_breakpoints(filename, {3}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is True
        assert decision["reason"] == "breakpoint_on_line"

    def test_invalidate_file_clears_conditions(self):
        analyzer = FrameTraceAnalyzer()
        filename = "/src/cond_invalidate.py"
        analyzer.set_breakpoint_conditions(filename, {1: "False"})
        analyzer.invalidate_file(filename)
        # After invalidation the condition map should be gone; breakpoint still hits.
        frame = _make_frame(filename, 1)
        with _with_breakpoints(filename, {1}):
            decision = analyzer.should_trace_frame(frame)
        assert decision["should_trace"] is True


# ---------------------------------------------------------------------------
# FrameTraceManager — set_conditional_breakpoints
# ---------------------------------------------------------------------------


class TestFrameTraceManagerConditional:
    def test_set_conditional_breakpoints_stores_and_gates(self):
        manager = FrameTraceManager()
        filename = "/src/mgr_cond.py"
        specs: list[ConditionalBreakpointSpec] = [
            {"lineno": 15, "condition": "x > 100"},
        ]
        manager.set_conditional_breakpoints(filename, specs)

        frame_hit = _make_frame(filename, 15, local_vars={"x": 200})
        frame_miss = _make_frame(filename, 15, local_vars={"x": 5})

        analyzer = manager.dispatcher.analyzer
        with _with_breakpoints(filename, {15}):
            assert analyzer.should_trace_frame(frame_hit)["should_trace"] is True
            assert analyzer.should_trace_frame(frame_miss)["should_trace"] is False

    def test_set_conditional_breakpoints_unconditional_spec(self):
        manager = FrameTraceManager()
        filename = "/src/mgr_uncond.py"
        specs: list[ConditionalBreakpointSpec] = [
            {"lineno": 8},  # no condition key
        ]
        manager.set_conditional_breakpoints(filename, specs)
        frame = _make_frame(filename, 8)
        with _with_breakpoints(filename, {8}):
            assert manager.dispatcher.analyzer.should_trace_frame(frame)["should_trace"] is True

    def test_get_breakpoints_reflects_conditional_spec(self):
        manager = FrameTraceManager()
        filename = "/src/mgr_bplist.py"
        specs: list[ConditionalBreakpointSpec] = [
            {"lineno": 10, "condition": "True"},
            {"lineno": 20},
        ]
        manager.set_conditional_breakpoints(filename, specs)
        assert manager.get_breakpoints(filename) == {10, 20}
