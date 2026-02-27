"""Tests for the VariableManager class."""

from __future__ import annotations

from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.variable_manager import VariableManager


class TestVariableManager:
    def test_initial_state(self):
        manager = VariableManager()
        assert manager.next_var_ref == 1000
        assert manager.var_refs == {}

    def test_custom_start_ref(self):
        manager = VariableManager(start_ref=5000)
        assert manager.next_var_ref == 5000

    def test_allocate_ref_dict(self):
        manager = VariableManager()
        ref = manager.allocate_ref({"key": "value"})
        assert ref == 1000
        assert manager.next_var_ref == 1001
        assert manager.var_refs[ref] == ("object", {"key": "value"})

    def test_allocate_ref_list(self):
        manager = VariableManager()
        my_list = [1, 2, 3]
        ref = manager.allocate_ref(my_list)
        assert ref == 1000
        assert manager.var_refs[ref] == ("object", my_list)

    def test_allocate_ref_tuple(self):
        manager = VariableManager()
        my_tuple = (1, 2, 3)
        ref = manager.allocate_ref(my_tuple)
        assert ref == 1000

    def test_allocate_ref_object_with_dict(self):
        manager = VariableManager()

        class MyClass:
            def __init__(self):
                self.value = 42

        obj = MyClass()
        ref = manager.allocate_ref(obj)
        assert ref == 1000

    def test_allocate_ref_primitive_returns_zero(self):
        manager = VariableManager()
        assert manager.allocate_ref(42) == 0
        assert manager.allocate_ref("string") == 0
        assert manager.allocate_ref(3.14) == 0
        assert manager.allocate_ref(True) == 0
        assert manager.allocate_ref(None) == 0

    def test_allocate_ref_increments(self):
        manager = VariableManager()
        ref1 = manager.allocate_ref({})
        ref2 = manager.allocate_ref([])
        ref3 = manager.allocate_ref(())
        assert ref1 == 1000
        assert ref2 == 1001
        assert ref3 == 1002

    def test_allocate_scope_ref(self):
        manager = VariableManager()
        ref = manager.allocate_scope_ref(frame_id=123, scope="locals")
        assert ref == 1000
        assert manager.var_refs[ref] == (123, "locals")

    def test_get_ref(self):
        manager = VariableManager()
        my_dict = {"x": 1}
        ref = manager.allocate_ref(my_dict)
        result = manager.get_ref(ref)
        assert result == ("object", my_dict)

    def test_get_ref_not_found(self):
        manager = VariableManager()
        assert manager.get_ref(9999) is None

    def test_has_ref(self):
        manager = VariableManager()
        ref = manager.allocate_ref({})
        assert manager.has_ref(ref) is True
        assert manager.has_ref(9999) is False

    def test_clear(self):
        manager = VariableManager()
        manager.allocate_ref({})
        manager.allocate_ref([])
        manager.clear()
        assert manager.var_refs == {}
        assert manager.next_var_ref == 1000


class TestVariableManagerMakeVariable:
    def test_make_variable_primitive(self):
        manager = VariableManager()
        var = manager.make_variable("x", 42)
        assert var["name"] == "x"
        assert var["value"] == "42"
        assert var["type"] == "int"
        assert var["variablesReference"] == 0

    def test_make_variable_string(self):
        manager = VariableManager()
        var = manager.make_variable("msg", "hello")
        assert var["value"] == "'hello'"
        assert var["type"] == "str"

    def test_make_variable_dict_expandable(self):
        manager = VariableManager()
        var = manager.make_variable("data", {"a": 1})
        assert var["variablesReference"] == 1000

    def test_make_variable_long_string_truncated(self):
        manager = VariableManager()
        long_str = "x" * 2000
        var = manager.make_variable("s", long_str, max_string_length=100)
        assert len(var["value"]) < 150  # truncated with "..."
        assert var["value"].endswith("...")

    def test_make_variable_multiline_has_raw_string_attr(self):
        manager = VariableManager()
        var = manager.make_variable("s", "line1\nline2")
        hint = var.get("presentationHint", {})
        attrs = hint.get("attributes", [])
        assert "rawString" in attrs

    def test_make_variable_callable_has_side_effects(self):
        manager = VariableManager()
        var = manager.make_variable("fn", lambda x: x)
        hint = var.get("presentationHint", {})
        assert hint.get("kind") == "method"
        assert "hasSideEffects" in hint.get("attributes", [])

    def test_make_variable_class_type(self):
        manager = VariableManager()

        class MyClass:
            pass

        var = manager.make_variable("cls", MyClass)
        hint = var.get("presentationHint", {})
        assert hint.get("kind") == "class"

    def test_make_variable_private_visibility(self):
        manager = VariableManager()
        var = manager.make_variable("_private", 1)
        hint = var.get("presentationHint", {})
        assert hint.get("visibility") == "private"

    def test_make_variable_public_visibility(self):
        manager = VariableManager()
        var = manager.make_variable("public", 1)
        hint = var.get("presentationHint", {})
        assert hint.get("visibility") == "public"  # type: ignore[union-attr]

    def test_make_variable_with_data_breakpoint(self):
        manager = VariableManager()
        data_bp_state = DataBreakpointState()
        data_bp_state.register_watches(["x"])

        var = manager.make_variable("x", 42, data_bp_state=data_bp_state)
        hint = var.get("presentationHint", {})
        assert "hasDataBreakpoint" in hint.get("attributes", [])  # type: ignore[union-attr]

    def test_make_variable_without_data_breakpoint(self):
        manager = VariableManager()
        data_bp_state = DataBreakpointState()
        data_bp_state.register_watches(["y"])  # watching y, not x

        var = manager.make_variable("x", 42, data_bp_state=data_bp_state)
        hint = var.get("presentationHint", {})
        assert "hasDataBreakpoint" not in hint.get("attributes", [])  # type: ignore[union-attr]

    def test_make_variable_error_repr(self):
        manager = VariableManager()

        class BadRepr:
            def __repr__(self):
                raise ValueError("Cannot repr")

        var = manager.make_variable("bad", BadRepr())
        assert var["value"] == "<Error getting value>"
