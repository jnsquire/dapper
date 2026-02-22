"""Tests for BreakpointManager.

These tests verify the centralized breakpoint state management:
- Line breakpoint metadata
- Function breakpoints
- Custom breakpoints
"""

from __future__ import annotations

from dapper.core.breakpoint_manager import BreakpointManager
from dapper.core.breakpoint_manager import LineBreakpointMeta
from dapper.core.breakpoint_resolver import BreakpointMeta
from dapper.core.debugger_bdb import DebuggerBDB


class TestLineBreakpointMeta:
    """Tests for LineBreakpointMeta dataclass (alias for BreakpointMeta)."""

    def test_default_values(self):
        """Test that defaults are set correctly."""
        meta = LineBreakpointMeta()
        assert meta.condition is None
        assert meta.hit_condition is None
        assert meta.log_message is None
        assert meta.hit_count == 0

    def test_with_all_fields(self):
        """Test creation with all fields."""
        meta = LineBreakpointMeta(
            condition="x > 5",
            hit_condition=">= 3",
            log_message="Value: {x}",
            hit_count=2,
        )
        assert meta.condition == "x > 5"
        assert meta.hit_condition == ">= 3"
        assert meta.log_message == "Value: {x}"
        assert meta.hit_count == 2

    def test_increment_hit(self):
        """Test incrementing hit count."""
        meta = LineBreakpointMeta()
        assert meta.hit_count == 0
        assert meta.increment_hit() == 1
        assert meta.increment_hit() == 2
        assert meta.hit_count == 2

    def test_is_same_as_breakpoint_meta(self):
        """Test that LineBreakpointMeta is the same as BreakpointMeta."""
        assert LineBreakpointMeta is BreakpointMeta


class TestLineBreakpoints:
    """Tests for line breakpoint management."""

    def test_record_line_breakpoint_basic(self):
        """Test recording a basic line breakpoint."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 10)

        meta = mgr.get_line_meta("/test.py", 10)
        assert meta is not None
        assert meta["hit"] == 0
        assert meta["condition"] is None
        assert meta["hitCondition"] is None
        assert meta["logMessage"] is None

    def test_record_line_breakpoint_with_condition(self):
        """Test recording with a condition."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 15, condition="x > 5")

        meta = mgr.get_line_meta("/test.py", 15)
        assert meta is not None
        assert meta["condition"] == "x > 5"

    def test_record_line_breakpoint_with_hit_condition(self):
        """Test recording with a hit condition."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 20, hit_condition=">= 3")

        meta = mgr.get_line_meta("/test.py", 20)
        assert meta is not None
        assert meta["hitCondition"] == ">= 3"

    def test_record_line_breakpoint_with_log_message(self):
        """Test recording a logpoint."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 25, log_message="Value is {x}")

        meta = mgr.get_line_meta("/test.py", 25)
        assert meta is not None
        assert meta["logMessage"] == "Value is {x}"

    def test_record_line_breakpoint_all_options(self):
        """Test recording with all options."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint(
            "/test.py",
            30,
            condition="y != 0",
            hit_condition="== 10",
            log_message="Count: {count}",
        )

        meta = mgr.get_line_meta("/test.py", 30)
        assert meta is not None
        assert meta["condition"] == "y != 0"
        assert meta["hitCondition"] == "== 10"
        assert meta["logMessage"] == "Count: {count}"

    def test_get_line_meta_not_found(self):
        """Test getting metadata for non-existent breakpoint."""
        mgr = BreakpointManager()
        assert mgr.get_line_meta("/test.py", 100) is None

    def test_update_preserves_hit_count(self):
        """Test that updating a breakpoint preserves hit count."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 10, condition="a")

        # Manually set hit count
        meta = mgr.get_line_meta("/test.py", 10)
        meta["hit"] = 5  # type: ignore[index]

        # Update with new condition
        mgr.record_line_breakpoint("/test.py", 10, condition="b")

        meta = mgr.get_line_meta("/test.py", 10)
        assert meta is not None
        assert meta["hit"] == 5
        assert meta["condition"] == "b"

    def test_clear_line_meta_for_file(self):
        """Test clearing metadata for a file."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/a.py", 10)
        mgr.record_line_breakpoint("/a.py", 20)
        mgr.record_line_breakpoint("/b.py", 30)

        mgr.clear_line_meta_for_file("/a.py")

        assert mgr.get_line_meta("/a.py", 10) is None
        assert mgr.get_line_meta("/a.py", 20) is None
        assert mgr.get_line_meta("/b.py", 30) is not None

    def test_clear_line_meta_for_file_clears_path_index(self):
        """Test path index remains consistent after clearing file metadata."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/a.py", 11)
        mgr.record_line_breakpoint("/a.py", 12)
        mgr.record_line_breakpoint("/b.py", 21)

        assert "/a.py" in mgr._line_meta_by_path
        assert 11 in mgr._line_meta_by_path["/a.py"]

        mgr.clear_line_meta_for_file("/a.py")

        assert "/a.py" not in mgr._line_meta_by_path
        assert "/b.py" in mgr._line_meta_by_path
        assert mgr.get_line_meta("/a.py", 11) is None
        assert mgr.get_line_meta("/b.py", 21) is not None

    def test_increment_hit_count(self):
        """Test incrementing hit count."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", 10)

        assert mgr.increment_hit_count("/test.py", 10) == 1
        assert mgr.increment_hit_count("/test.py", 10) == 2
        assert mgr.increment_hit_count("/test.py", 10) == 3

    def test_increment_hit_count_non_existent(self):
        """Test incrementing hit count for non-existent breakpoint."""
        mgr = BreakpointManager()
        assert mgr.increment_hit_count("/test.py", 99) == 0

    def test_line_as_string_converted_to_int(self):
        """Test that line numbers are converted to int for key."""
        mgr = BreakpointManager()
        mgr.record_line_breakpoint("/test.py", "15")  # type: ignore[arg-type]

        # Should be accessible with int
        assert mgr.get_line_meta("/test.py", 15) is not None


class TestFunctionBreakpoints:
    """Tests for function breakpoint management."""

    def test_set_function_breakpoints_names_only(self):
        """Test setting function breakpoints by name."""
        mgr = BreakpointManager()
        mgr.set_function_breakpoints(["main", "helper"])

        assert "main" in mgr.function_names
        assert "helper" in mgr.function_names

    def test_set_function_breakpoints_with_meta(self):
        """Test setting function breakpoints with metadata."""
        mgr = BreakpointManager()
        metas = {
            "main": {"condition": "arg == 1"},
            "helper": {"hitCondition": ">= 5"},
        }
        mgr.set_function_breakpoints(["main", "helper"], metas)

        assert mgr.get_function_meta("main")["condition"] == "arg == 1"
        assert mgr.get_function_meta("helper")["hitCondition"] == ">= 5"

    def test_get_function_meta_not_found(self):
        """Test getting metadata for non-existent function breakpoint."""
        mgr = BreakpointManager()
        assert mgr.get_function_meta("unknown") == {}

    def test_set_function_breakpoints_replaces(self):
        """Test that set_function_breakpoints replaces existing."""
        mgr = BreakpointManager()
        mgr.set_function_breakpoints(["foo"])
        mgr.set_function_breakpoints(["bar"])

        assert "foo" not in mgr.function_names
        assert "bar" in mgr.function_names

    def test_clear_function_breakpoints(self):
        """Test clearing all function breakpoints."""
        mgr = BreakpointManager()
        mgr.set_function_breakpoints(["main"], {"main": {"condition": "x"}})

        mgr.clear_function_breakpoints()

        assert len(mgr.function_names) == 0
        assert len(mgr.function_meta) == 0

    def test_has_function_breakpoints(self):
        """Test checking for function breakpoints."""
        mgr = BreakpointManager()
        assert not mgr.has_function_breakpoints()

        mgr.set_function_breakpoints(["main"])
        assert mgr.has_function_breakpoints()

        mgr.clear_function_breakpoints()
        assert not mgr.has_function_breakpoints()


class TestCustomBreakpoints:
    """Tests for custom (programmatic) breakpoint management."""

    def test_set_custom_breakpoint_basic(self):
        """Test setting a custom breakpoint."""
        mgr = BreakpointManager()
        mgr.set_custom_breakpoint("/test.py", 10)

        assert mgr.has_custom_breakpoint("/test.py", 10)

    def test_set_custom_breakpoint_with_condition(self):
        """Test setting a custom breakpoint with condition."""
        mgr = BreakpointManager()
        mgr.set_custom_breakpoint("/test.py", 10, condition="x > 5")

        assert mgr.custom["/test.py"][10] == "x > 5"

    def test_clear_custom_breakpoint(self):
        """Test clearing a custom breakpoint."""
        mgr = BreakpointManager()
        mgr.set_custom_breakpoint("/test.py", 10)

        result = mgr.clear_custom_breakpoint("/test.py", 10)

        assert result is True
        assert not mgr.has_custom_breakpoint("/test.py", 10)

    def test_clear_custom_breakpoint_not_found(self):
        """Test clearing non-existent custom breakpoint."""
        mgr = BreakpointManager()
        result = mgr.clear_custom_breakpoint("/test.py", 99)
        assert result is False

    def test_has_custom_breakpoint_false(self):
        """Test has_custom_breakpoint returns False when not set."""
        mgr = BreakpointManager()
        assert not mgr.has_custom_breakpoint("/test.py", 10)

    def test_multiple_custom_breakpoints_same_file(self):
        """Test multiple custom breakpoints in same file."""
        mgr = BreakpointManager()
        mgr.set_custom_breakpoint("/test.py", 10)
        mgr.set_custom_breakpoint("/test.py", 20)
        mgr.set_custom_breakpoint("/test.py", 30)

        assert mgr.has_custom_breakpoint("/test.py", 10)
        assert mgr.has_custom_breakpoint("/test.py", 20)
        assert mgr.has_custom_breakpoint("/test.py", 30)

    def test_clear_all_custom_breakpoints(self):
        """Test clearing all custom breakpoints."""
        mgr = BreakpointManager()
        mgr.set_custom_breakpoint("/a.py", 10)
        mgr.set_custom_breakpoint("/b.py", 20)

        mgr.clear_all_custom_breakpoints()

        assert not mgr.has_custom_breakpoint("/a.py", 10)
        assert not mgr.has_custom_breakpoint("/b.py", 20)


class TestClearAll:
    """Tests for clearing all breakpoint state."""

    def test_clear_all(self):
        """Test clear_all clears everything."""
        mgr = BreakpointManager()

        # Set up various breakpoints
        mgr.record_line_breakpoint("/test.py", 10, condition="x")
        mgr.set_function_breakpoints(["main"])
        mgr.set_custom_breakpoint("/test.py", 20)

        mgr.clear_all()

        assert len(mgr.line_meta) == 0
        assert len(mgr.function_names) == 0
        assert len(mgr.function_meta) == 0
        assert len(mgr.custom) == 0


class TestDebuggerBDBIntegration:
    """Tests for integration with DebuggerBDB via compatibility properties."""

    def test_compatibility_properties_line_meta(self):
        """Test that breakpoint_meta property works."""
        dbg = DebuggerBDB()
        dbg.bp_manager.line_meta[("/test.py", 10)] = {"hit": 0}

        assert dbg.bp_manager.line_meta[("/test.py", 10)]["hit"] == 0

    def test_compatibility_properties_function_breakpoints(self):
        """Test that function breakpoints work through delegate."""
        dbg = DebuggerBDB()
        dbg.bp_manager.function_names = ["main", "helper"]

        assert "main" in dbg.bp_manager.function_names
        assert "helper" in dbg.bp_manager.function_names

    def test_compatibility_properties_function_meta(self):
        """Test that function_breakpoint_meta works through delegate."""
        dbg = DebuggerBDB()
        dbg.bp_manager.function_meta["main"] = {"condition": "x > 0"}

        assert dbg.bp_manager.function_meta["main"]["condition"] == "x > 0"

    def test_compatibility_properties_custom_breakpoints(self):
        """Test that custom_breakpoints property works."""
        dbg = DebuggerBDB()
        dbg.bp_manager.custom["/test.py"] = {10: None}

        assert dbg.bp_manager.custom["/test.py"][10] is None

    def test_record_breakpoint_method(self):
        """Test that record_breakpoint method works."""
        dbg = DebuggerBDB()
        dbg.record_breakpoint(
            "/test.py",
            10,
            condition="x > 5",
            hit_condition=">= 3",
            log_message="Value: {x}",
        )

        meta = dbg.bp_manager.line_meta.get(("/test.py", 10))
        assert meta is not None
        assert meta["condition"] == "x > 5"
        assert meta["hitCondition"] == ">= 3"
        assert meta["logMessage"] == "Value: {x}"

    def test_clear_break_meta_for_file_method(self):
        """Test that clear_break_meta_for_file method works."""
        dbg = DebuggerBDB()
        dbg.record_breakpoint("/a.py", 10, condition=None, hit_condition=None, log_message=None)
        dbg.record_breakpoint("/a.py", 20, condition=None, hit_condition=None, log_message=None)
        dbg.record_breakpoint("/b.py", 30, condition=None, hit_condition=None, log_message=None)

        dbg.clear_break_meta_for_file("/a.py")

        assert ("/a.py", 10) not in dbg.bp_manager.line_meta
        assert ("/a.py", 20) not in dbg.bp_manager.line_meta
        assert ("/b.py", 30) in dbg.bp_manager.line_meta

    def test_set_custom_breakpoint_method(self):
        """Test that set_custom_breakpoint method works."""
        dbg = DebuggerBDB()
        dbg.set_custom_breakpoint("/test.py", 10, condition="x > 0")

        assert "/test.py" in dbg.bp_manager.custom
        assert 10 in dbg.bp_manager.custom["/test.py"]

    def test_clear_custom_breakpoint_method(self):
        """Test that clear_custom_breakpoint method works."""
        dbg = DebuggerBDB()
        dbg.set_custom_breakpoint("/test.py", 10)
        dbg.clear_custom_breakpoint("/test.py", 10)

        assert "/test.py" not in dbg.bp_manager.custom or 10 not in dbg.bp_manager.custom.get(
            "/test.py",
            {},
        )

    def test_clear_all_custom_breakpoints_method(self):
        """Test that clear_all_custom_breakpoints method works."""
        dbg = DebuggerBDB()
        dbg.set_custom_breakpoint("/a.py", 10)
        dbg.set_custom_breakpoint("/b.py", 20)

        dbg.clear_all_custom_breakpoints()

        assert len(dbg.bp_manager.custom) == 0

    def test_clear_all_function_breakpoints_method(self):
        """Test that clear_all_function_breakpoints method works."""
        dbg = DebuggerBDB()
        dbg.bp_manager.function_names = ["main"]
        dbg.bp_manager.function_meta["main"] = {"condition": "x"}

        dbg.clear_all_function_breakpoints()

        assert len(dbg.bp_manager.function_names) == 0
        assert len(dbg.bp_manager.function_meta) == 0
