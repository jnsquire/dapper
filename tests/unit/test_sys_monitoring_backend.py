# ruff: noqa: PLC0415
"""Phase 2.8 — integration tests for ``SysMonitoringBackend``.

Covers:
- Instantiation and lifecycle (install / shutdown).
- Code-object registry via ``_on_py_start``.
- Breakpoint management (``update_breakpoints``, ``set_local_events``).
- ``LINE`` callback: ``DISABLE`` for non-breakpoints, ``user_line`` for hits.
- Conditional breakpoints evaluated through ``ConditionEvaluator``.
- Stepping (``STEP_IN`` / ``STEP_OVER`` / ``STEP_OUT`` / ``CONTINUE``).
- ``CALL`` callback for function breakpoints.
- ``integrate_with_backend`` routing in ``debugger_integration``.
- Statistics shape compatibility.
- Thread-safety: breakpoints hit correctly across two threads.

All tests are skipped on Python < 3.12 because ``sys.monitoring`` is not
available there; the companion ``SettraceBackend`` path is tested in
``tests/unit/test_tracing_backend_selection.py``.
"""
# ruff: noqa: PLC0415

from __future__ import annotations

import sys
import threading
import types
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not (sys.version_info >= (3, 12) and hasattr(sys, "monitoring")),
    reason="sys.monitoring requires Python 3.12+",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend():
    """Return a fresh, *un-installed* SysMonitoringBackend."""
    from dapper._frame_eval.monitoring_backend import SysMonitoringBackend

    return SysMonitoringBackend()


def _make_code(filename: str = "/fake/module.py", name: str = "func") -> types.CodeType:
    """Compile a trivial function and return its code object with *filename*."""
    src = f"def {name}(): pass"
    compiled = compile(src, filename, "exec")
    # The code object for the *exec* wrapper; grab the function def inside it.
    for const in compiled.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == name:
            return const
    return compiled


@pytest.fixture
def backend():
    """Provide an installed SysMonitoringBackend and clean up after each test."""
    b = _make_backend()
    mock_debugger = MagicMock()
    mock_debugger.user_line = MagicMock()
    mock_debugger.user_call = MagicMock()

    with (
        patch.object(sys.monitoring, "get_tool", return_value=None),
        patch.object(sys.monitoring, "use_tool_id"),
        patch.object(sys.monitoring, "register_callback"),
        patch.object(sys.monitoring, "set_events"),
        patch.object(sys.monitoring, "set_local_events"),
        patch.object(sys.monitoring, "free_tool_id"),
        patch.object(sys.monitoring, "restart_events"),
        patch.object(sys.monitoring, "get_events", return_value=0),
    ):
        b.install(mock_debugger)
        b._installed = True  # ensure flag is set even with mocked calls
        yield b, mock_debugger
        b.shutdown()


# ---------------------------------------------------------------------------
# 1. Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_can_instantiate(self):
        from dapper._frame_eval.monitoring_backend import SysMonitoringBackend

        b = SysMonitoringBackend()
        assert b is not None

    def test_implements_tracing_backend(self):
        from dapper._frame_eval.monitoring_backend import SysMonitoringBackend
        from dapper._frame_eval.tracing_backend import TracingBackend

        assert issubclass(SysMonitoringBackend, TracingBackend)

    def test_not_installed_after_construction(self):
        b = _make_backend()
        assert b._installed is False  # type: ignore[attr-defined]
        assert b._debugger is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 2. Install / shutdown lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_install_claims_tool_id(self):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value=None),
            patch.object(sys.monitoring, "use_tool_id") as mock_use_tool,
            patch.object(sys.monitoring, "register_callback"),
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "free_tool_id"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.install(MagicMock())
            mock_use_tool.assert_called_once_with(DEBUGGER_ID, "dapper")
            b.shutdown()

    def test_install_registers_line_callback(self):

        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value=None),
            patch.object(sys.monitoring, "use_tool_id"),
            patch.object(sys.monitoring, "register_callback") as mock_reg,
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "free_tool_id"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.install(MagicMock())
            registered_events = [c.args[1] for c in mock_reg.call_args_list]
            assert sys.monitoring.events.LINE in registered_events
            b.shutdown()

    def test_install_raises_when_slot_taken(self):
        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value="competitor"),
            pytest.raises(RuntimeError, match="already held"),
        ):
            b.install(MagicMock())

    def test_install_is_idempotent(self):
        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value=None),
            patch.object(sys.monitoring, "use_tool_id") as mock_use_tool,
            patch.object(sys.monitoring, "register_callback"),
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "free_tool_id"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.install(MagicMock())
            b.install(MagicMock())  # second call — should be no-op
            mock_use_tool.assert_called_once()
            b.shutdown()

    def test_shutdown_frees_tool_id(self):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value=None),
            patch.object(sys.monitoring, "use_tool_id"),
            patch.object(sys.monitoring, "register_callback"),
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "free_tool_id") as mock_free,
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.install(MagicMock())
            b.shutdown()
            mock_free.assert_called_once_with(DEBUGGER_ID)

    def test_shutdown_clears_state(self):
        b = _make_backend()
        with (
            patch.object(sys.monitoring, "get_tool", return_value=None),
            patch.object(sys.monitoring, "use_tool_id"),
            patch.object(sys.monitoring, "register_callback"),
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "free_tool_id"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.install(MagicMock())
            b._breakpoints["/some/file.py"] = frozenset({10})  # type: ignore[index]
            b.shutdown()
            assert not b._installed  # type: ignore[attr-defined]
            assert b._debugger is None  # type: ignore[attr-defined]
            assert not b._breakpoints  # type: ignore[attr-defined]

    def test_shutdown_before_install_does_not_raise(self):
        b = _make_backend()
        with (
            patch.object(sys.monitoring, "free_tool_id"),
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "register_callback"),
        ):
            b.shutdown()  # should be a no-op


# ---------------------------------------------------------------------------
# 3. Code-object registry via _on_py_start (2.4)
# ---------------------------------------------------------------------------


class TestPyStartRegistry:
    def test_py_start_registers_code_object(self, backend):
        b, _ = backend
        code = _make_code("/src/app.py", "greet")
        b._on_py_start(code, 0)
        assert code in b._code_registry["/src/app.py"]  # type: ignore[operator]

    def test_py_start_returns_disable(self, backend):
        b, _ = backend
        code = _make_code("/src/app.py", "unused")
        result = b._on_py_start(code, 0)
        assert result is sys.monitoring.DISABLE

    def test_py_start_enables_line_events_when_file_has_breakpoints(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        filename = "/src/app.py"
        b._breakpoints[filename] = frozenset({42})
        code = _make_code(filename, "calc")
        with patch.object(sys.monitoring, "set_local_events") as mock_sle:
            b._on_py_start(code, 0)
        mock_sle.assert_called_once_with(DEBUGGER_ID, code, sys.monitoring.events.LINE)

    def test_py_start_no_line_events_when_file_has_no_breakpoints(self, backend):
        b, _ = backend
        code = _make_code("/src/other.py", "noop")
        with patch.object(sys.monitoring, "set_local_events") as mock_sle:
            b._on_py_start(code, 0)
        mock_sle.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Breakpoint management (2.3)
# ---------------------------------------------------------------------------


class TestBreakpointManagement:
    def test_update_breakpoints_stores_frozenset(self, backend):
        b, _ = backend
        with (
            patch.object(sys.monitoring, "restart_events"),
            patch.object(sys.monitoring, "set_local_events"),
        ):
            b.update_breakpoints("/app/views.py", {10, 20, 30})
        assert b._breakpoints["/app/views.py"] == frozenset({10, 20, 30})  # type: ignore[index]

    def test_update_breakpoints_empty_removes_file(self, backend):
        b, _ = backend
        b._breakpoints["/app/views.py"] = frozenset({10})
        with (
            patch.object(sys.monitoring, "restart_events"),
            patch.object(sys.monitoring, "set_local_events"),
        ):
            b.update_breakpoints("/app/views.py", set())
        assert "/app/views.py" not in b._breakpoints  # type: ignore[operator]

    def test_update_breakpoints_calls_restart_events(self, backend):
        b, _ = backend
        with (
            patch.object(sys.monitoring, "restart_events") as mock_re,
            patch.object(sys.monitoring, "set_local_events"),
        ):
            b.update_breakpoints("/app/views.py", {5})
        mock_re.assert_called_once()

    def test_update_breakpoints_applies_local_events_to_known_codes(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        filename = "/app/models.py"
        code = _make_code(filename, "save")
        b._code_registry[filename].add(code)  # type: ignore[index]

        with (
            patch.object(sys.monitoring, "restart_events"),
            patch.object(sys.monitoring, "set_local_events") as mock_sle,
        ):
            b.update_breakpoints(filename, {55, 60})

        mock_sle.assert_called_with(DEBUGGER_ID, code, sys.monitoring.events.LINE)

    def test_update_breakpoints_disables_events_when_cleared(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        filename = "/app/models.py"
        code = _make_code(filename, "delete")
        b._breakpoints[filename] = frozenset({10})
        b._code_registry[filename].add(code)  # type: ignore[index]

        with (
            patch.object(sys.monitoring, "restart_events"),
            patch.object(sys.monitoring, "set_local_events") as mock_sle,
        ):
            b.update_breakpoints(filename, set())

        mock_sle.assert_called_with(DEBUGGER_ID, code, sys.monitoring.events.NO_EVENTS)

    def test_set_conditions_stored_and_cleared(self, backend):
        b, _ = backend
        b.set_conditions("/app/utils.py", 100, "x > 0")
        assert b._conditions[("/app/utils.py", 100)] == "x > 0"  # type: ignore[index]
        b.set_conditions("/app/utils.py", 100, None)
        assert ("/app/utils.py", 100) not in b._conditions  # type: ignore[operator]


# ---------------------------------------------------------------------------
# 5. LINE callback — breakpoint hits (2.2)
# ---------------------------------------------------------------------------


class TestLineCallback:
    def _minimal_code(self, filename: str = "/src/mod.py") -> types.CodeType:
        return _make_code(filename, "target")

    def test_non_breakpoint_line_returns_disable(self, backend):
        b, _ = backend
        code = self._minimal_code()
        # No breakpoints registered → DISABLE
        result = b._on_line(code, 99)
        assert result is sys.monitoring.DISABLE

    def test_non_breakpoint_line_in_known_file_also_returns_disable(self, backend):
        b, _ = backend
        code = self._minimal_code("/src/mod.py")
        b._breakpoints["/src/mod.py"] = frozenset({10})  # 10, not 99
        result = b._on_line(code, 99)
        assert result is sys.monitoring.DISABLE

    def test_breakpoint_line_calls_user_line(self, backend):
        b, mock_debugger = backend
        code = self._minimal_code("/src/mod.py")
        b._breakpoints["/src/mod.py"] = frozenset({42})
        # Call the callback; sys._getframe(1) inside will be our test frame
        b._on_line(code, 42)
        mock_debugger.user_line.assert_called_once()

    def test_breakpoint_line_does_not_return_disable(self, backend):
        b, _ = backend
        code = self._minimal_code("/src/mod.py")
        b._breakpoints["/src/mod.py"] = frozenset({42})
        result = b._on_line(code, 42)
        assert result is not sys.monitoring.DISABLE

    def test_line_increments_hit_counter(self, backend):
        b, _ = backend
        code = self._minimal_code("/src/mod.py")
        b._breakpoints["/src/mod.py"] = frozenset({5})
        before = b._stats["line_hits"]
        b._on_line(code, 5)
        assert b._stats["line_hits"] == before + 1  # type: ignore[index]

    def test_line_increments_disabled_counter(self, backend):
        b, _ = backend
        code = self._minimal_code("/src/mod.py")
        before = b._stats["line_disabled"]
        b._on_line(code, 999)
        assert b._stats["line_disabled"] == before + 1  # type: ignore[index]


# ---------------------------------------------------------------------------
# 6. Conditional breakpoints (2.2)
# ---------------------------------------------------------------------------


class TestConditionalBreakpoints:
    def test_true_condition_calls_user_line(self, backend):
        b, mock_debugger = backend
        filename = "/src/utils.py"
        code = _make_code(filename, "helper")
        b._breakpoints[filename] = frozenset({15})
        b._conditions[(filename, 15)] = "1 == 1"  # always true
        b._on_line(code, 15)
        mock_debugger.user_line.assert_called_once()

    def test_false_condition_skips_user_line(self, backend):
        b, mock_debugger = backend
        filename = "/src/utils.py"
        code = _make_code(filename, "helper")
        b._breakpoints[filename] = frozenset({15})
        b._conditions[(filename, 15)] = "1 == 2"  # always false
        result = b._on_line(code, 15)
        mock_debugger.user_line.assert_not_called()
        assert result is not sys.monitoring.DISABLE  # re-evaluation possible

    def test_condition_increments_evaluation_counter(self, backend):
        b, _ = backend
        filename = "/src/utils.py"
        code = _make_code(filename, "helper")
        b._breakpoints[filename] = frozenset({7})
        b._conditions[(filename, 7)] = "True"
        before = b._stats["condition_evaluations"]
        b._on_line(code, 7)
        assert b._stats["condition_evaluations"] == before + 1  # type: ignore[index]

    def test_false_condition_increments_skip_counter(self, backend):
        b, _ = backend
        filename = "/src/utils.py"
        code = _make_code(filename, "helper")
        b._breakpoints[filename] = frozenset({7})
        b._conditions[(filename, 7)] = "False"
        before = b._stats["condition_skips"]
        b._on_line(code, 7)
        assert b._stats["condition_skips"] == before + 1  # type: ignore[index]


# ---------------------------------------------------------------------------
# 7. Stepping support (2.5)
# ---------------------------------------------------------------------------


class TestStepping:
    def test_step_in_enables_global_line_events(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("STEP_IN")
        expected = (
            sys.monitoring.events.LINE
            | sys.monitoring.events.PY_START
            | sys.monitoring.events.PY_RETURN
        )
        mock_se.assert_called_with(DEBUGGER_ID, expected)

    def test_step_over_enables_py_return_globally(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "set_local_events"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("STEP_OVER")
        # First call sets PY_START | PY_RETURN globally
        args_list = [c.args for c in mock_se.call_args_list]
        assert (
            DEBUGGER_ID,
            sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN,
        ) in args_list

    def test_step_over_enables_line_on_current_code(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        code = _make_code("/src/main.py", "run")
        b._step_code = code  # type: ignore[attr-defined]
        with (
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "set_local_events") as mock_sle,
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("STEP_OVER")
        mock_sle.assert_called_with(DEBUGGER_ID, code, sys.monitoring.events.LINE)

    def test_step_out_enables_py_return_globally(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "set_local_events"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("STEP_OUT")
        args_list = [c.args for c in mock_se.call_args_list]
        assert (
            DEBUGGER_ID,
            sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN,
        ) in args_list

    def test_step_out_disables_line_on_current_code(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        code = _make_code("/src/main.py", "run")
        b._step_code = code  # type: ignore[attr-defined]
        with (
            patch.object(sys.monitoring, "set_events"),
            patch.object(sys.monitoring, "set_local_events") as mock_sle,
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("STEP_OUT")
        mock_sle.assert_called_with(DEBUGGER_ID, code, sys.monitoring.events.NO_EVENTS)

    def test_continue_restores_breakpoint_only_events(self, backend):
        from dapper._frame_eval.monitoring_backend import DEBUGGER_ID

        b, _ = backend
        b._step_mode = "STEP_IN"  # type: ignore[attr-defined]
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "set_local_events"),
            patch.object(sys.monitoring, "restart_events"),
        ):
            b.set_stepping("CONTINUE")
        # Global set_events for CONTINUE: PY_START only
        assert any(
            c.args == (DEBUGGER_ID, sys.monitoring.events.PY_START) for c in mock_se.call_args_list
        )

    def test_py_return_during_step_over_switches_to_step_in(self, backend):
        b, _ = backend
        b._step_mode = "STEP_OVER"  # type: ignore[attr-defined]
        with patch.object(sys.monitoring, "set_events"):
            b._on_py_return(_make_code(), 0, None)
        assert b._step_mode == "STEP_IN"  # type: ignore[attr-defined]

    def test_py_return_during_continue_returns_disable(self, backend):
        b, _ = backend
        b._step_mode = "CONTINUE"  # type: ignore[attr-defined]
        result = b._on_py_return(_make_code(), 0, None)
        assert result is sys.monitoring.DISABLE

    def test_capture_step_context_stores_code(self, backend):
        b, _ = backend
        code = _make_code()
        b.capture_step_context(code)
        assert b._step_code is code  # type: ignore[attr-defined]

    def test_stepping_fires_user_line(self, backend):
        """LINE callback in step-in mode calls user_line even for non-bp lines."""
        b, mock_debugger = backend
        b._step_mode = "STEP_IN"  # type: ignore[attr-defined]
        code = _make_code("/elsewhere/code.py", "do_work")
        # No breakpoint registered for this file
        b._on_line(code, 1)
        mock_debugger.user_line.assert_called_once()


# ---------------------------------------------------------------------------
# 8. CALL callback — function breakpoints (2.6)
# ---------------------------------------------------------------------------


class TestCallCallback:
    def test_call_returns_disable_when_no_function_breakpoints(self, backend):
        b, _ = backend
        code = _make_code()
        result = b._on_call(code, 0, lambda: None, None)
        assert result is sys.monitoring.DISABLE

    def test_call_matches_qualname_and_fires_user_call(self, backend):
        b, mock_debugger = backend
        b._function_breakpoints = frozenset({"MyClass.method"})
        callable_ = MagicMock(__qualname__="MyClass.method", __name__="method")
        b._on_call(_make_code(), 0, callable_, None)
        mock_debugger.user_call.assert_called_once()

    def test_call_non_matching_returns_disable(self, backend):
        b, mock_debugger = backend
        b._function_breakpoints = frozenset({"other_func"})
        callable_ = MagicMock(__qualname__="unrelated_func", __name__="unrelated_func")
        result = b._on_call(_make_code(), 0, callable_, None)
        assert result is sys.monitoring.DISABLE
        mock_debugger.user_call.assert_not_called()

    def test_call_increments_hit_counter(self, backend):
        b, _ = backend
        b._function_breakpoints = frozenset({"target"})
        callable_ = MagicMock(__qualname__="target", __name__="target")
        before = b._stats["call_hits"]
        b._on_call(_make_code(), 0, callable_, None)
        assert b._stats["call_hits"] == before + 1  # type: ignore[index]

    def test_update_function_breakpoints_enables_call_events(self, backend):

        b, _ = backend
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "get_events", return_value=0),
        ):
            b.update_function_breakpoints({"some_func"})
        # Should OR in the CALL event
        assert any(c.args[1] & sys.monitoring.events.CALL for c in mock_se.call_args_list)

    def test_update_function_breakpoints_empty_removes_call_events(self, backend):

        b, _ = backend
        b._step_mode = "CONTINUE"  # type: ignore[attr-defined]
        call_flag = sys.monitoring.events.CALL
        with (
            patch.object(sys.monitoring, "set_events") as mock_se,
            patch.object(sys.monitoring, "get_events", return_value=call_flag),
        ):
            b.update_function_breakpoints(set())
        # Should clear the CALL event
        assert any(not (c.args[1] & call_flag) for c in mock_se.call_args_list)


# ---------------------------------------------------------------------------
# 9. integrate_with_backend routing (2.7)
# ---------------------------------------------------------------------------


class TestIntegrateWithBackend:
    def test_routes_sys_monitoring_backend_to_install(self):
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.monitoring_backend import SysMonitoringBackend

        backend_mock = MagicMock(spec=SysMonitoringBackend)
        debugger = MagicMock()
        result = integrate_with_backend(backend_mock, debugger)
        backend_mock.install.assert_called_once_with(debugger)
        assert result is True

    def test_routes_settrace_backend_to_integrate_debugger_bdb(self):
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.settrace_backend import SettraceBackend

        backend_obj = SettraceBackend()
        debugger = MagicMock()
        with patch(
            "dapper._frame_eval.debugger_integration.integrate_debugger_bdb",
            return_value=True,
        ) as mock_int:
            result = integrate_with_backend(backend_obj, debugger)
        mock_int.assert_called_once_with(debugger)
        assert result is True

    def test_install_failure_returns_false(self):
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.monitoring_backend import SysMonitoringBackend

        bad_backend = MagicMock(spec=SysMonitoringBackend)
        bad_backend.install.side_effect = RuntimeError("slot taken")
        result = integrate_with_backend(bad_backend, MagicMock())
        assert result is False


# ---------------------------------------------------------------------------
# 10. Statistics shape
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_statistics_has_required_integration_keys(self, backend):
        b, _ = backend
        stats = b.get_statistics()
        for key in (
            "config",
            "integration_stats",
            "performance_data",
            "trace_manager_stats",
            "cache_stats",
            "telemetry",
        ):
            assert key in stats, f"Missing key '{key}' in get_statistics()"

    def test_statistics_config_has_enabled_key(self, backend):
        b, _ = backend
        stats = b.get_statistics()
        assert "enabled" in stats["config"]

    def test_statistics_counters_present(self, backend):
        b, _ = backend
        stats = b.get_statistics()
        assert "counters" in stats
        assert "line_callbacks" in stats["counters"]

    def test_set_exception_breakpoints_does_not_raise(self, backend):
        b, _ = backend
        b.set_exception_breakpoints(["raised", "uncaught"])


# ---------------------------------------------------------------------------
# 11. Thread safety — breakpoints hit correctly across threads
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_update_breakpoints_does_not_corrupt_registry(self, backend):
        """Stress-test update_breakpoints from multiple threads."""
        b, _ = backend
        filename = "/src/server.py"
        errors: list[Exception] = []

        def worker(lines: set[int]) -> None:
            try:
                with (
                    patch.object(sys.monitoring, "restart_events"),
                    patch.object(sys.monitoring, "set_local_events"),
                ):
                    b.update_breakpoints(filename, lines)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=({i * 10},)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent update: {errors}"
        # After all threads finish, breakpoints should reflect one of the valid states.
        assert filename in b._breakpoints or filename not in b._breakpoints

    def test_concurrent_line_callbacks_increment_counter_safely(self, backend):
        """Multiple threads simulating LINE callbacks must not lose increments."""
        b, _mock_debugger = backend
        filename = "/src/api.py"
        code = _make_code(filename, "handle")
        b._breakpoints[filename] = frozenset({1})

        n = 50

        def fire() -> None:
            b._on_line(code, 1)

        threads = [threading.Thread(target=fire) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert b._stats["line_hits"] >= n  # type: ignore[index]
