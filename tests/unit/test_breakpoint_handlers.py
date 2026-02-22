"""Tests for dapper/shared/breakpoint_handlers.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from dapper.shared.breakpoint_handlers import handle_set_breakpoints_impl
from dapper.shared.breakpoint_handlers import handle_set_exception_breakpoints_impl
from dapper.shared.breakpoint_handlers import handle_set_function_breakpoints_impl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logger() -> MagicMock:
    return MagicMock()


def _make_safe_send() -> MagicMock:
    return MagicMock()


def _make_dbg(
    *,
    set_break_result: Any = True,
    clear_raises: bool = False,
) -> MagicMock:
    dbg = MagicMock()
    if clear_raises:
        dbg.clear_breaks_for_file.side_effect = AttributeError("no attr")
        dbg.clear_break.side_effect = AttributeError("no attr")
        dbg.clear_break_meta_for_file.side_effect = AttributeError("no attr")
    dbg.set_break.return_value = set_break_result
    dbg.bp_manager = MagicMock()
    dbg.bp_manager.function_names = []
    dbg.bp_manager.function_meta = {}
    return dbg


class TestHandleSetBreakpointsImpl:
    def test_no_dbg_returns_none(self) -> None:
        result = handle_set_breakpoints_impl(
            None,
            {"source": {"path": "/x/y.py"}, "breakpoints": [{"line": 5}]},
            _make_safe_send(),
            _make_logger(),
        )
        assert result is None

    def test_no_path_returns_none(self) -> None:
        dbg = _make_dbg()
        result = handle_set_breakpoints_impl(
            dbg,
            {"source": {}, "breakpoints": [{"line": 5}]},
            _make_safe_send(),
            _make_logger(),
        )
        assert result is None

    def test_basic_breakpoint_set(self) -> None:
        dbg = _make_dbg(set_break_result=None)  # None → verified=True (not False)
        send = _make_safe_send()

        result = handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 10}],
            },
            send,
            _make_logger(),
        )

        assert result is not None
        assert result["success"] is True
        bps = result["body"]["breakpoints"]
        assert len(bps) == 1
        assert bps[0]["verified"] is True
        assert bps[0]["line"] == 10

    def test_breakpoint_not_verified_when_set_break_returns_false(self) -> None:
        dbg = _make_dbg(set_break_result=False)
        result = handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 10}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        assert result is not None
        bps = result["body"]["breakpoints"]
        assert bps[0]["verified"] is False

    def test_breakpoint_not_verified_when_set_break_raises(self) -> None:
        dbg = _make_dbg()
        dbg.set_break.side_effect = RuntimeError("cannot set")
        result = handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 5}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        assert result is not None
        bps = result["body"]["breakpoints"]
        assert bps[0]["verified"] is False

    def test_multiple_breakpoints(self) -> None:
        dbg = _make_dbg()
        result = handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 1}, {"line": 2}, {"line": 3}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        assert result is not None
        assert len(result["body"]["breakpoints"]) == 3

    def test_clears_existing_breakpoints_before_setting(self) -> None:
        dbg = _make_dbg()
        handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 10}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        dbg.clear_breaks_for_file.assert_called_once_with("/app/main.py")

    def test_clear_fallback_chain(self) -> None:
        """If clear_breaks_for_file raises, falls back to clear_break and then clear_break_meta_for_file."""
        dbg = _make_dbg(clear_raises=True)
        # Should not raise — all clear methods fail gracefully
        result = handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 5}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        assert result is not None

    def test_condition_passed_to_set_break(self) -> None:
        dbg = _make_dbg()
        handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 10, "condition": "x > 5"}],
            },
            _make_safe_send(),
            _make_logger(),
        )
        dbg.set_break.assert_called_once_with("/app/main.py", 10, cond="x > 5")

    def test_safe_send_called_with_breakpoints(self) -> None:
        dbg = _make_dbg()
        send = _make_safe_send()
        handle_set_breakpoints_impl(
            dbg,
            {
                "source": {"path": "/app/main.py"},
                "breakpoints": [{"line": 1}],
            },
            send,
            _make_logger(),
        )
        send.assert_called_once()
        call_args = send.call_args
        assert call_args[0][0] == "breakpoints"

    def test_empty_breakpoints_list(self) -> None:
        dbg = _make_dbg()
        result = handle_set_breakpoints_impl(
            dbg,
            {"source": {"path": "/app/main.py"}, "breakpoints": []},
            _make_safe_send(),
            _make_logger(),
        )
        assert result is not None
        assert result["body"]["breakpoints"] == []

    def test_arguments_none_treated_as_empty(self) -> None:
        result = handle_set_breakpoints_impl(
            None,
            None,
            _make_safe_send(),
            _make_logger(),
        )
        assert result is None


class TestHandleSetFunctionBreakpointsImpl:
    def test_no_dbg_returns_none(self) -> None:
        result = handle_set_function_breakpoints_impl(None, {"breakpoints": [{"name": "my_func"}]})
        assert result is None

    def test_sets_function_breakpoint(self) -> None:
        dbg = _make_dbg()
        result = handle_set_function_breakpoints_impl(dbg, {"breakpoints": [{"name": "my_func"}]})
        assert result is not None
        assert result["success"] is True
        bps = result["body"]["breakpoints"]
        assert len(bps) == 1
        assert bps[0]["verified"] is True
        assert "my_func" in dbg.bp_manager.function_names

    def test_clears_existing_before_setting(self) -> None:
        dbg = _make_dbg()
        handle_set_function_breakpoints_impl(dbg, {"breakpoints": [{"name": "fn"}]})
        dbg.clear_all_function_breakpoints.assert_called_once()

    def test_multiple_function_breakpoints(self) -> None:
        dbg = _make_dbg()
        result = handle_set_function_breakpoints_impl(
            dbg,
            {"breakpoints": [{"name": "fn1"}, {"name": "fn2"}]},
        )
        assert result is not None
        assert len(result["body"]["breakpoints"]) == 2
        assert all(bp["verified"] for bp in result["body"]["breakpoints"])

    def test_breakpoint_without_name_is_skipped(self) -> None:
        dbg = _make_dbg()
        result = handle_set_function_breakpoints_impl(
            dbg,
            {"breakpoints": [{"name": ""}, {"condition": "x>1"}]},  # no name
        )
        # Nothing added to function_names, results still built from bps list
        assert result is not None
        assert len(result["body"]["breakpoints"]) == 2
        # Both should be unverified (name missing)
        assert all(not bp["verified"] for bp in result["body"]["breakpoints"])

    def test_metadata_stored_on_function_breakpoint(self) -> None:
        dbg = _make_dbg()
        handle_set_function_breakpoints_impl(
            dbg,
            {
                "breakpoints": [
                    {
                        "name": "fn",
                        "condition": "x == 1",
                        "hitCondition": "3",
                        "logMessage": "hit!",
                    },
                ],
            },
        )
        meta = dbg.bp_manager.function_meta.get("fn", {})
        assert meta.get("condition") == "x == 1"
        assert meta.get("hitCondition") == "3"
        assert meta.get("logMessage") == "hit!"

    def test_arguments_none_treated_as_empty(self) -> None:
        dbg = _make_dbg()
        result = handle_set_function_breakpoints_impl(dbg, None)
        assert result is not None
        assert result["body"]["breakpoints"] == []


class TestHandleSetExceptionBreakpointsImpl:
    def _make_exception_dbg(self) -> MagicMock:
        dbg = MagicMock()
        dbg.exception_handler = MagicMock()
        dbg.exception_handler.config = MagicMock()
        dbg.exception_handler.config.break_on_raised = False
        dbg.exception_handler.config.break_on_uncaught = False
        return dbg

    def test_no_dbg_returns_none(self) -> None:
        result = handle_set_exception_breakpoints_impl(None, {"filters": ["raised"]})
        assert result is None

    def test_raised_filter_sets_break_on_raised(self) -> None:
        dbg = self._make_exception_dbg()
        result = handle_set_exception_breakpoints_impl(dbg, {"filters": ["raised"]})
        assert dbg.exception_handler.config.break_on_raised is True
        assert dbg.exception_handler.config.break_on_uncaught is False
        assert result is not None
        assert result["success"] is True

    def test_uncaught_filter_sets_break_on_uncaught(self) -> None:
        dbg = self._make_exception_dbg()
        handle_set_exception_breakpoints_impl(dbg, {"filters": ["uncaught"]})
        assert dbg.exception_handler.config.break_on_raised is False
        assert dbg.exception_handler.config.break_on_uncaught is True

    def test_both_filters_sets_both_flags(self) -> None:
        dbg = self._make_exception_dbg()
        handle_set_exception_breakpoints_impl(dbg, {"filters": ["raised", "uncaught"]})
        assert dbg.exception_handler.config.break_on_raised is True
        assert dbg.exception_handler.config.break_on_uncaught is True

    def test_empty_filters_clears_both_flags(self) -> None:
        dbg = self._make_exception_dbg()
        dbg.exception_handler.config.break_on_raised = True
        dbg.exception_handler.config.break_on_uncaught = True
        handle_set_exception_breakpoints_impl(dbg, {"filters": []})
        assert dbg.exception_handler.config.break_on_raised is False
        assert dbg.exception_handler.config.break_on_uncaught is False

    def test_breakpoints_list_matches_filters_length(self) -> None:
        dbg = self._make_exception_dbg()
        result = handle_set_exception_breakpoints_impl(dbg, {"filters": ["raised", "uncaught"]})
        assert result is not None
        assert len(result["body"]["breakpoints"]) == 2

    def test_attribute_error_on_exception_handler_gives_unverified(self) -> None:
        class _BadConfig:
            @property
            def break_on_raised(self) -> bool:
                raise AttributeError("no config")

            @break_on_raised.setter
            def break_on_raised(self, _v: bool) -> None:
                raise AttributeError("no config")

        class _BadHandler:
            config = _BadConfig()

        dbg = MagicMock()
        dbg.exception_handler = _BadHandler()
        result = handle_set_exception_breakpoints_impl(dbg, {"filters": ["raised"]})
        assert result is not None
        assert result["body"]["breakpoints"][0]["verified"] is False

    def test_non_list_filters_treated_as_empty(self) -> None:
        dbg = self._make_exception_dbg()
        result = handle_set_exception_breakpoints_impl(dbg, {"filters": "raised"})  # type: ignore[arg-type]
        assert result is not None
        assert result["body"]["breakpoints"] == []

    def test_arguments_none_treated_as_empty(self) -> None:
        dbg = self._make_exception_dbg()
        result = handle_set_exception_breakpoints_impl(dbg, None)
        assert result is not None
        assert result["body"]["breakpoints"] == []
