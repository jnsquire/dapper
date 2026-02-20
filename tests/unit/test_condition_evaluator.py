"""Tests for ConditionEvaluator (conditional breakpoint fast-path)."""

from __future__ import annotations

from unittest.mock import MagicMock

from dapper._frame_eval.condition_evaluator import ConditionEvaluator
from dapper._frame_eval.condition_evaluator import get_condition_evaluator
from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry


def _make_frame(local_vars: dict) -> MagicMock:
    """Return a minimal mock frame with the given local variables."""
    frame = MagicMock()
    frame.f_locals = local_vars
    frame.f_globals = {}
    return frame


class TestConditionEvaluator:
    # ------------------------------------------------------------------
    # Basic pass / fail
    # ------------------------------------------------------------------

    def test_always_true_expression_passes(self):
        ev = ConditionEvaluator()
        result = ev.evaluate("True", _make_frame({}))
        assert result["passed"] is True
        assert result["fallback"] is False
        assert result["error"] is None

    def test_always_false_expression_is_blocked(self):
        ev = ConditionEvaluator()
        result = ev.evaluate("False", _make_frame({}))
        assert result["passed"] is False
        assert result["fallback"] is False

    def test_condition_uses_frame_locals(self):
        ev = ConditionEvaluator()
        frame_true = _make_frame({"x": 10})
        frame_false = _make_frame({"x": 1})
        assert ev.evaluate("x > 5", frame_true)["passed"] is True
        assert ev.evaluate("x > 5", frame_false)["passed"] is False

    # ------------------------------------------------------------------
    # Error and fallback paths
    # ------------------------------------------------------------------

    def test_syntax_error_falls_back_to_trace(self):
        ev = ConditionEvaluator()
        result = ev.evaluate("this is not valid python !!!", _make_frame({}))
        assert result["passed"] is True  # conservative: trace the frame
        assert result["fallback"] is True
        assert result["error"] is not None

    def test_runtime_error_falls_back_to_trace(self):
        ev = ConditionEvaluator()
        # NameError: undefined_var is not in scope
        result = ev.evaluate("undefined_var > 0", _make_frame({}))
        assert result["passed"] is True
        assert result["fallback"] is True
        assert "NameError" in (result["error"] or "")

    def test_syntax_error_records_reason_code(self):
        reset_frame_eval_telemetry()
        ev = ConditionEvaluator()
        ev.evaluate(")(invalid", _make_frame({}))
        snap = get_frame_eval_telemetry()
        assert snap.reason_counts.selective_tracing_analysis_failed >= 1

    def test_runtime_error_records_reason_code(self):
        reset_frame_eval_telemetry()
        ev = ConditionEvaluator()
        ev.evaluate("no_such_name", _make_frame({}))
        snap = get_frame_eval_telemetry()
        assert snap.reason_counts.selective_tracing_analysis_failed >= 1

    # ------------------------------------------------------------------
    # Compilation cache
    # ------------------------------------------------------------------

    def test_expression_is_compiled_once(self):
        ev = ConditionEvaluator()
        assert ev.cache_size() == 0
        ev.evaluate("1 + 1 == 2", _make_frame({}))
        ev.evaluate("1 + 1 == 2", _make_frame({}))
        assert ev.cache_size() == 1

    def test_clear_cache(self):
        ev = ConditionEvaluator()
        ev.evaluate("True", _make_frame({}))
        ev.clear_cache()
        assert ev.cache_size() == 0

    # ------------------------------------------------------------------
    # Disabled evaluator
    # ------------------------------------------------------------------

    def test_disabled_evaluator_always_passes(self):
        ev = ConditionEvaluator(enabled=False)
        result = ev.evaluate("False", _make_frame({}))
        assert result["passed"] is True
        assert result["fallback"] is True
        assert result["elapsed_s"] == 0.0

    def test_enable_disable_toggle(self):
        ev = ConditionEvaluator(enabled=True)
        ev.enabled = False
        assert ev.evaluate("False", _make_frame({}))["passed"] is True
        ev.enabled = True
        assert ev.evaluate("False", _make_frame({}))["passed"] is False

    # ------------------------------------------------------------------
    # Module-level singleton
    # ------------------------------------------------------------------

    def test_get_condition_evaluator_returns_singleton(self):
        a = get_condition_evaluator()
        b = get_condition_evaluator()
        assert a is b
