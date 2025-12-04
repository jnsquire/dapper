"""Tests for expression completions feature.

Tests the completions implementation across:
- InProcessDebugger._get_runtime_completions
- InProcessDebugger.completions 
- DAP request handler integration
"""
from __future__ import annotations

import os as os_module
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.core.inprocess_debugger import InProcessDebugger

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeFrame:
    """Minimal frame mock for testing."""

    def __init__(
        self, locals_: dict[str, Any] | None = None, globals_: dict[str, Any] | None = None
    ):
        self.f_locals = locals_ or {}
        self.f_globals = globals_ or {}


class FakeDebugger:
    """Minimal debugger mock for testing."""

    def __init__(self) -> None:
        self.frame_id_to_frame: dict[int, FakeFrame] = {}


def labels_from_targets(targets: Sequence[Any]) -> list[str]:
    """Small helper to extract `label` fields from a list of completion targets.

    This helper is defensive — it will ignore non-dicts and targets missing
    a `label` field. Tests expect a plain list of strings, so we cast to str
    for typing clarity.
    """
    return [cast("str", t["label"]) for t in targets if isinstance(t, dict) and "label" in t and t["label"] is not None]


class TestExpressionExtraction:
    """Tests for _extract_completion_expr helper."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()

    def test_empty_text(self) -> None:
        assert self.ip._extract_completion_expr("") == ""

    def test_simple_identifier(self) -> None:
        assert self.ip._extract_completion_expr("foo") == "foo"
        assert self.ip._extract_completion_expr("my_var") == "my_var"

    def test_attribute_access(self) -> None:
        assert self.ip._extract_completion_expr("obj.") == "obj."
        assert self.ip._extract_completion_expr("obj.attr") == "obj.attr"
        assert self.ip._extract_completion_expr("obj.sub.attr") == "obj.sub.attr"

    def test_after_operator(self) -> None:
        assert self.ip._extract_completion_expr("x + y") == "y"
        assert self.ip._extract_completion_expr("x = foo") == "foo"
        assert self.ip._extract_completion_expr("a * b.") == "b."

    def test_inside_function_call(self) -> None:
        assert self.ip._extract_completion_expr("print(x") == "x"
        assert self.ip._extract_completion_expr("foo(a, b") == "b"
        assert self.ip._extract_completion_expr("foo(bar.") == "bar."

    def test_nested_brackets(self) -> None:
        assert self.ip._extract_completion_expr("foo[bar]") == "foo[bar]"
        assert self.ip._extract_completion_expr("foo(bar(baz).") == "bar(baz)."

    def test_with_whitespace(self) -> None:
        assert self.ip._extract_completion_expr("  x") == "x"
        assert self.ip._extract_completion_expr("x +  y") == "y"


class TestCompletionTypeInference:
    """Tests for _infer_completion_type helper."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()

    def test_none_is_value(self) -> None:
        assert self.ip._infer_completion_type(None) == "value"

    def test_class_detection(self) -> None:
        assert self.ip._infer_completion_type(int) == "class"
        assert self.ip._infer_completion_type(str) == "class"

        class MyClass:
            pass

        assert self.ip._infer_completion_type(MyClass) == "class"

    def test_module_detection(self) -> None:
        assert self.ip._infer_completion_type(os_module) == "module"

    def test_function_detection(self) -> None:
        def my_func() -> None:
            pass

        assert self.ip._infer_completion_type(my_func) == "function"
        assert self.ip._infer_completion_type(len) == "function"  # builtin

    def test_method_detection(self) -> None:

        class Foo:
            def method(self) -> None:
                pass

        obj = Foo()
        assert self.ip._infer_completion_type(obj.method) == "method"

    def test_callable_detection(self) -> None:

        class Callable:
            def __call__(self) -> None:
                pass

        assert self.ip._infer_completion_type(Callable()) == "function"

    def test_variable_fallback(self) -> None:
        assert self.ip._infer_completion_type(42) == "variable"
        assert self.ip._infer_completion_type("string") == "variable"
        assert self.ip._infer_completion_type([1, 2, 3]) == "variable"


class TestRuntimeCompletions:
    """Tests for _get_runtime_completions with frame context."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()

    def test_simple_name_completion_from_locals(self) -> None:
        local_ns = {"foo": 1, "foobar": 2, "baz": 3}
        global_ns: dict[str, Any] = {}

        targets = self.ip._get_runtime_completions("foo", local_ns, global_ns)

        labels = labels_from_targets(targets)
        assert "foo" in labels
        assert "foobar" in labels
        assert "baz" not in labels

    def test_name_completion_from_globals(self) -> None:
        local_ns: dict[str, Any] = {}
        global_ns = {"my_global": 42}

        targets = self.ip._get_runtime_completions("my_", local_ns, global_ns)

        labels = labels_from_targets(targets)
        assert "my_global" in labels

    def test_name_completion_from_builtins(self) -> None:
        targets = self.ip._get_runtime_completions("pr", {}, {})

        labels = labels_from_targets(targets)
        assert "print" in labels

    def test_locals_shadow_globals(self) -> None:
        local_ns = {"value": "local"}
        global_ns = {"value": "global", "value2": "global2"}

        targets = self.ip._get_runtime_completions("val", local_ns, global_ns)

        # Should have value (once, from locals) and value2
        labels = labels_from_targets(targets)
        assert labels.count("value") == 1
        assert "value2" in labels

    def test_attribute_completion(self) -> None:
        local_ns = {"obj": "hello"}
        global_ns: dict[str, Any] = {}

        targets = self.ip._get_runtime_completions("obj.upp", local_ns, global_ns)

        labels = labels_from_targets(targets)
        assert "upper" in labels

    def test_attribute_completion_all_attrs(self) -> None:
        local_ns = {"obj": [1, 2, 3]}
        global_ns: dict[str, Any] = {}

        targets = self.ip._get_runtime_completions("obj.", local_ns, global_ns)

        labels = labels_from_targets(targets)
        assert "append" in labels
        assert "pop" in labels
        assert "sort" in labels

    def test_attribute_completion_invalid_base(self) -> None:
        targets = self.ip._get_runtime_completions("undefined_var.", {}, {})

        # Should return empty list if base can't be evaluated
        assert targets == []

    def test_completion_type_hints(self) -> None:
        def my_func() -> None:
            pass

        local_ns = {"my_func": my_func}

        targets = self.ip._get_runtime_completions("my_", local_ns, {})

        target = next(
            (t for t in targets if isinstance(t, dict) and t.get("label") == "my_func"),
            None,
        )
        assert target is not None
        assert target.get("type") == "function"

    def test_sorted_results(self) -> None:
        local_ns = {"zebra": 1, "apple": 2, "mango": 3}

        targets = self.ip._get_runtime_completions("", local_ns, {})

        # Filter to just our test variables
        our_labels = [l for l in labels_from_targets(targets) if l in local_ns]
        assert our_labels == sorted(our_labels)


class TestCompletionsAPI:
    """Tests for the high-level completions() method."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()
        self.fake = FakeDebugger()
        self.ip.debugger = cast("Any", self.fake)

    def test_completions_with_frame(self) -> None:
        frame = FakeFrame(locals_={"my_var": 42})
        self.fake.frame_id_to_frame[1] = frame

        result = self.ip.completions("my_", column=4, frame_id=1)

        assert "targets" in result
        labels = labels_from_targets(result.get("targets", []))
        assert "my_var" in labels

    def test_completions_without_frame(self) -> None:
        # No frame_id provided - should use builtins only
        result = self.ip.completions("pri", column=4, frame_id=None)

        labels = labels_from_targets(result.get("targets", []))
        assert "print" in labels

    def test_completions_multiline_text(self) -> None:
        frame = FakeFrame(locals_={"x": 1, "y": 2})
        self.fake.frame_id_to_frame[1] = frame

        # Multi-line text, cursor on line 2
        text = "line1\nx"
        result = self.ip.completions(text, column=2, frame_id=1, line=2)

        labels = labels_from_targets(result.get("targets", []))
        assert "x" in labels

    def test_completions_empty_prefix(self) -> None:
        frame = FakeFrame(locals_={"a": 1, "b": 2})
        self.fake.frame_id_to_frame[1] = frame

        result = self.ip.completions("", column=1, frame_id=1)

        # Should return all available names
        labels = labels_from_targets(result.get("targets", []))
        assert "a" in labels
        assert "b" in labels

    def test_completions_invalid_frame_id(self) -> None:
        # Frame doesn't exist - should fallback to builtins
        result = self.ip.completions("pri", column=4, frame_id=999)

        labels = labels_from_targets(result.get("targets", []))
        assert "print" in labels


class TestCompletionItem:
    """Tests for _make_completion_item helper."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()

    def test_basic_item(self) -> None:
        item = self.ip._make_completion_item("foo", 42, "variable")

        assert item.get("label") == "foo"
        assert item.get("type") == "variable"
        assert "detail" in item

    def test_function_signature_in_detail(self) -> None:
        def my_func(a: int, b: str) -> None:
            pass

        item = self.ip._make_completion_item("my_func", my_func, "function")

        assert "my_func" in item.get("detail", "")
        # Should contain signature info
        assert "a" in item.get("detail", "") or "..." in item.get("detail", "")

    def test_class_type_in_detail(self) -> None:
        item = self.ip._make_completion_item("int", int, "class")

        assert item.get("type") == "class"


class TestAttributeCompletion:
    """Tests for _complete_attributes helper."""

    def setup_method(self) -> None:
        self.ip = InProcessDebugger()

    def test_complete_string_attrs(self) -> None:
        targets = self.ip._complete_attributes("hello", "up")

        labels = labels_from_targets(targets)
        assert "upper" in labels

    def test_complete_list_attrs(self) -> None:
        targets = self.ip._complete_attributes([1, 2], "app")

        labels = labels_from_targets(targets)
        assert "append" in labels

    def test_complete_all_attrs(self) -> None:
        targets = self.ip._complete_attributes(42, "")

        # Should include all int methods
        labels = labels_from_targets(targets)
        assert "__add__" in labels
        assert "__str__" in labels

    def test_handles_property_errors(self) -> None:

        class BadProperty:
            @property
            def bad_attr(self) -> None:
                raise RuntimeError("Can't access")

        obj = BadProperty()
        # Should not raise, should still include the attribute
        targets = self.ip._complete_attributes(obj, "bad")

        labels = labels_from_targets(targets)
        assert "bad_attr" in labels
