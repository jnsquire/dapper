"""Tests for the BreakpointResolver class."""

from __future__ import annotations

from dapper.core.breakpoint_resolver import BreakpointMeta
from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.breakpoint_resolver import ResolveResult
from dapper.core.breakpoint_resolver import get_resolver
from tests.mocks import make_real_frame


def make_frame(_filename: str, _lineno: int, locals_dict: dict, globals_dict: dict | None = None):
    # Use real paused frame with given locals for testing.
    frame = make_real_frame(locals_dict)
    # set f_globals if provided
    if globals_dict is not None:
        frame.f_globals.clear()
        frame.f_globals.update(globals_dict)
    return frame


class TestBreakpointMeta:
    def test_defaults(self):
        meta = BreakpointMeta()
        assert meta.condition is None
        assert meta.hit_condition is None
        assert meta.log_message is None
        assert meta.hit_count == 0

    def test_increment_hit(self):
        meta = BreakpointMeta()
        assert meta.increment_hit() == 1
        assert meta.increment_hit() == 2
        assert meta.hit_count == 2


class TestResolveResult:
    def test_should_stop(self):
        result = ResolveResult(ResolveAction.STOP)
        assert result.should_stop is True
        assert result.should_continue is False

    def test_should_continue(self):
        result = ResolveResult(ResolveAction.CONTINUE)
        assert result.should_stop is False
        assert result.should_continue is True

    def test_skip(self):
        result = ResolveResult(ResolveAction.SKIP)
        assert result.should_stop is False
        assert result.should_continue is False


class TestBreakpointResolver:
    def test_none_meta_returns_stop(self):
        resolver = BreakpointResolver()
        result = resolver.resolve(None)
        assert result.action == ResolveAction.STOP

    def test_empty_meta_returns_stop(self):
        resolver = BreakpointResolver()
        result = resolver.resolve(BreakpointMeta())
        assert result.action == ResolveAction.STOP

    def test_condition_true_stops(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 5})
        meta = BreakpointMeta(condition="x > 3")
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.STOP

    def test_condition_false_continues(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 1})
        meta = BreakpointMeta(condition="x > 3")
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.CONTINUE
        assert "condition not met" in result.reason

    def test_condition_error_continues(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 1})
        meta = BreakpointMeta(condition="undefined_var > 3")
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.CONTINUE

    def test_hit_condition_equal(self):
        resolver = BreakpointResolver()
        meta = BreakpointMeta(hit_condition="==3", hit_count=0)

        # Hits 1, 2 should continue
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE

        # Hit 3 should stop
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.STOP

    def test_hit_condition_modulo(self):
        resolver = BreakpointResolver()
        meta = BreakpointMeta(hit_condition="%2", hit_count=0)

        # Hit 1 - odd, continues
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE

        # Hit 2 - even, stops
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.STOP

        # Hit 3 - odd, continues
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE

    def test_hit_condition_gte(self):
        resolver = BreakpointResolver()
        meta = BreakpointMeta(hit_condition=">=3", hit_count=0)

        # Hits 1, 2 should continue
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.CONTINUE

        # Hits 3+ should stop
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.STOP
        result = resolver.resolve(meta)
        assert result.action == ResolveAction.STOP

    def test_logpoint_emits_and_continues(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 42})
        meta = BreakpointMeta(log_message="Value of x: {x}")

        emitted: list[tuple[str, str]] = []

        def emit(category: str, output: str) -> None:
            emitted.append((category, output))

        result = resolver.resolve(meta, frame, emit_output=emit)
        assert result.action == ResolveAction.CONTINUE
        assert result.log_output == "Value of x: 42"
        assert emitted == [("console", "Value of x: 42")]

    def test_logpoint_without_emitter(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 42})
        meta = BreakpointMeta(log_message="Value: {x}")
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.CONTINUE
        assert result.log_output == "Value: 42"

    def test_dict_meta_conversion(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 5})
        meta_dict = {"condition": "x > 3", "hitCondition": None, "hit": 0}
        result = resolver.resolve(meta_dict, frame)
        assert result.action == ResolveAction.STOP
        # Dict should be updated with hit count
        assert meta_dict["hit"] == 1

    def test_dict_meta_hit_writeback(self):
        resolver = BreakpointResolver()
        meta_dict = {"condition": None, "hitCondition": ">=2", "hit": 0}

        # First hit continues
        result = resolver.resolve(meta_dict)
        assert result.action == ResolveAction.CONTINUE
        assert meta_dict["hit"] == 1

        # Second hit stops
        result = resolver.resolve(meta_dict)
        assert result.action == ResolveAction.STOP
        assert meta_dict["hit"] == 2

    def test_should_stop_convenience_method(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 5})
        assert resolver.should_stop(BreakpointMeta(condition="x > 3"), frame) is True
        assert resolver.should_stop(BreakpointMeta(condition="x < 3"), frame) is False

    def test_combined_condition_and_hit(self):
        resolver = BreakpointResolver()
        frame = make_frame("test.py", 10, {"x": 5})
        meta = BreakpointMeta(condition="x > 3", hit_condition=">=2", hit_count=0)

        # Hit 1 - hit condition not met
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.CONTINUE

        # Hit 2 - both conditions met
        result = resolver.resolve(meta, frame)
        assert result.action == ResolveAction.STOP

    def test_condition_without_frame(self):
        resolver = BreakpointResolver()
        meta = BreakpointMeta(condition="x > 3")
        result = resolver.resolve(meta, frame=None)
        # Cannot evaluate condition without frame - treated as not met
        assert result.action == ResolveAction.CONTINUE

    def test_auto_increment_disabled(self):
        resolver = BreakpointResolver()
        meta = BreakpointMeta(hit_count=5)
        resolver.resolve(meta, auto_increment_hit=False)
        assert meta.hit_count == 5  # Not incremented


class TestGetResolver:
    def test_returns_singleton(self):
        r1 = get_resolver()
        r2 = get_resolver()
        assert r1 is r2

    def test_is_breakpoint_resolver(self):
        assert isinstance(get_resolver(), BreakpointResolver)
