"""Tests for the DataBreakpointState class."""

from __future__ import annotations

from dapper.core.data_breakpoint_state import DataBreakpointState


class TestDataBreakpointState:
    def test_initial_state(self):
        state = DataBreakpointState()
        assert state.watch_names == set()
        assert state.watch_meta == {}
        assert state.last_values_by_frame == {}
        assert state.global_values == {}
        assert state.data_watches == {}
        assert state.frame_watches == {}

    def test_has_watches_empty(self):
        state = DataBreakpointState()
        assert state.has_watches() is False

    def test_register_watches_simple(self):
        state = DataBreakpointState()
        state.register_watches(["x", "y", "z"])

        assert state.watch_names == {"x", "y", "z"}
        assert state.has_watches() is True
        assert state.is_watching("x") is True
        assert state.is_watching("w") is False

    def test_register_watches_with_meta(self):
        state = DataBreakpointState()
        metas = [
            ("x", {"condition": "x > 5", "hitCondition": None}),
            ("x", {"condition": None, "hitCondition": ">=3"}),
            ("y", {"condition": "y == 0"}),
        ]
        state.register_watches(["x", "y"], metas)

        assert state.watch_names == {"x", "y"}
        assert len(state.watch_meta["x"]) == 2
        assert len(state.watch_meta["y"]) == 1
        assert state.watch_meta["x"][0]["condition"] == "x > 5"

    def test_register_watches_filters_invalid(self):
        state = DataBreakpointState()
        state.register_watches(["x", "", None, 123, "y"])  # pyright: ignore[reportArgumentType]
        assert state.watch_names == {"x", "y"}

    def test_get_meta_for_name(self):
        state = DataBreakpointState()
        state.register_watches(["x"], [("x", {"condition": "x > 0"})])

        assert len(state.get_meta_for_name("x")) == 1
        assert state.get_meta_for_name("y") == []

    def test_clear(self):
        state = DataBreakpointState()
        state.register_watches(["x", "y"])
        state.global_values["x"] = 42
        state.last_values_by_frame[123] = {"x": 1}
        state.data_watches["id1"] = {"name": "x"}
        state.frame_watches[456] = ["id1"]

        state.clear()

        assert state.watch_names == set()
        assert state.watch_meta == {}
        assert state.global_values == {}
        assert state.last_values_by_frame == {}
        assert state.data_watches == {}
        assert state.frame_watches == {}

    def test_clear_value_snapshots(self):
        state = DataBreakpointState()
        state.register_watches(["x"])
        state.global_values["x"] = 42
        state.last_values_by_frame[123] = {"x": 1}

        state.clear_value_snapshots()

        # Watch config preserved
        assert state.watch_names == {"x"}
        # Values cleared
        assert state.global_values == {}
        assert state.last_values_by_frame == {}

    def test_check_for_changes_no_watches(self):
        state = DataBreakpointState()
        assert state.check_for_changes(1, {"x": 5}) == []

    def test_check_for_changes_no_prior(self):
        state = DataBreakpointState()
        state.register_watches(["x"])

        # First call - no prior value, so no change detected
        assert state.check_for_changes(1, {"x": 5}) == []

    def test_check_for_changes_detects_change(self):
        state = DataBreakpointState()
        state.register_watches(["x"])

        # Establish baseline
        state.update_snapshots(1, {"x": 5})

        # Now change the value
        changed = state.check_for_changes(1, {"x": 10})
        assert changed == ["x"]

    def test_check_for_changes_no_change(self):
        state = DataBreakpointState()
        state.register_watches(["x"])

        state.update_snapshots(1, {"x": 5})
        changed = state.check_for_changes(1, {"x": 5})
        assert changed == []

    def test_check_for_changes_uses_global_fallback(self):
        state = DataBreakpointState()
        state.register_watches(["x"])

        # Update snapshots with frame 1
        state.update_snapshots(1, {"x": 5})

        # Check with different frame - should use global fallback
        changed = state.check_for_changes(2, {"x": 10})
        assert changed == ["x"]

    def test_check_for_changes_variable_not_in_locals(self):
        state = DataBreakpointState()
        state.register_watches(["x", "y"])

        state.update_snapshots(1, {"x": 5})

        # y is watched but not in locals - no change reported for y
        changed = state.check_for_changes(1, {"x": 10})
        assert changed == ["x"]

    def test_update_snapshots(self):
        state = DataBreakpointState()
        state.register_watches(["x", "y"])

        state.update_snapshots(1, {"x": 5, "y": 10, "z": 15})

        # Per-frame snapshot
        assert state.last_values_by_frame[1] == {"x": 5, "y": 10}

        # Global snapshot
        assert state.global_values == {"x": 5, "y": 10}

    def test_update_snapshots_no_watches(self):
        state = DataBreakpointState()
        state.update_snapshots(1, {"x": 5})

        # Nothing should be stored
        assert state.last_values_by_frame == {}
        assert state.global_values == {}

    def test_has_data_breakpoint_for_name_watch_names(self):
        state = DataBreakpointState()
        state.register_watches(["x"])

        assert state.has_data_breakpoint_for_name("x") is True
        assert state.has_data_breakpoint_for_name("y") is False

    def test_has_data_breakpoint_for_name_watch_meta(self):
        state = DataBreakpointState()
        state.watch_meta["x"] = [{"condition": "x > 0"}]

        assert state.has_data_breakpoint_for_name("x") is True

    def test_has_data_breakpoint_for_name_frame_watches(self):
        state = DataBreakpointState()
        state.frame_watches[123] = ["scope:var:x", "other:var:y"]

        assert state.has_data_breakpoint_for_name("x", frame_id=123) is True
        assert state.has_data_breakpoint_for_name("y", frame_id=123) is True
        assert state.has_data_breakpoint_for_name("z", frame_id=123) is False

    def test_has_data_breakpoint_for_name_no_frame_id(self):
        state = DataBreakpointState()
        state.frame_watches[123] = ["scope:var:x"]

        # Without frame_id, frame_watches are not checked
        assert state.has_data_breakpoint_for_name("x") is False


class TestDataBreakpointStateIntegration:
    """Integration tests simulating real debugging scenarios."""

    def test_watch_lifecycle(self):
        state = DataBreakpointState()

        # 1. Register watches
        state.register_watches(["counter"], [("counter", {"condition": "counter > 0"})])
        assert state.has_watches()

        # 2. First execution - establish baseline
        state.update_snapshots(1, {"counter": 0})
        assert state.check_for_changes(1, {"counter": 0}) == []

        # 3. Value changes
        assert state.check_for_changes(1, {"counter": 1}) == ["counter"]
        state.update_snapshots(1, {"counter": 1})

        # 4. Same value - no change
        assert state.check_for_changes(1, {"counter": 1}) == []

        # 5. Clear watches
        state.clear()
        assert not state.has_watches()
