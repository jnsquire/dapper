"""Tests for structured model rendering (dataclass / namedtuple / Pydantic).

Covers:
- Detection helpers in ``dapper.core.structured_model``
- ``VariableManager.make_variable()`` producing ``namedVariables`` and a
  descriptive type label for structured types
- Field-level ``presentationHint.kind == "property"`` in both
  ``command_handler_helpers.extract_variables`` and
  ``resolve_variables_for_reference``
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar
from typing import NamedTuple

from dapper.core.structured_model import get_model_fields
from dapper.core.structured_model import is_dataclass_instance
from dapper.core.structured_model import is_namedtuple_instance
from dapper.core.structured_model import is_pydantic_instance
from dapper.core.structured_model import is_structured_model
from dapper.core.structured_model import structured_model_label
from dapper.core.variable_manager import VariableManager
from dapper.shared import command_handler_helpers

# ---------------------------------------------------------------------------
# Sample types used across the tests
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Point:
    x: float
    y: float


@dataclasses.dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    debug: bool = False


class SimpleNT(NamedTuple):
    a: int
    b: int
    c: int


class TypedNT(NamedTuple):
    name: str
    value: int


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


class TestIsDataclassInstance:
    def test_dataclass_instance_is_detected(self):
        assert is_dataclass_instance(Point(1.0, 2.0))

    def test_dataclass_class_itself_is_not_an_instance(self):
        assert not is_dataclass_instance(Point)

    def test_non_dataclass_is_false(self):
        assert not is_dataclass_instance(42)
        assert not is_dataclass_instance("hello")
        assert not is_dataclass_instance([1, 2, 3])


class TestIsNamedtupleInstance:
    def test_simple_namedtuple(self):
        assert is_namedtuple_instance(SimpleNT(1, 2, 3))

    def test_typed_namedtuple(self):
        assert is_namedtuple_instance(TypedNT("x", 1))

    def test_plain_tuple_is_not_namedtuple(self):
        assert not is_namedtuple_instance((1, 2, 3))

    def test_dataclass_is_not_namedtuple(self):
        assert not is_namedtuple_instance(Point(0.0, 0.0))

    def test_empty_namedtuple(self):
        class Empty(NamedTuple):
            pass

        assert is_namedtuple_instance(Empty())


class TestIsStructuredModel:
    def test_dataclass(self):
        assert is_structured_model(Point(0, 0))

    def test_namedtuple(self):
        assert is_structured_model(SimpleNT(1, 2, 3))

    def test_class_itself_is_excluded(self):
        assert not is_structured_model(Point)

    def test_plain_dict_is_not_structured(self):
        assert not is_structured_model({"a": 1})

    def test_plain_list_is_not_structured(self):
        assert not is_structured_model([1, 2])

    def test_int_is_not_structured(self):
        assert not is_structured_model(42)


class TestIsPydanticInstance:
    def test_non_pydantic_object_is_false(self):
        class Plain:
            pass

        assert not is_pydantic_instance(Plain())

    def test_duck_typed_pydantic_v2_detected(self):
        """A class with model_fields dict is treated as a Pydantic v2 model."""

        class FakeV2:
            model_fields: ClassVar = {"x": None}

        assert is_pydantic_instance(FakeV2())

    def test_duck_typed_pydantic_v1_detected(self):
        """A class with __fields__ and __validators__ is treated as Pydantic v1."""

        class FakeV1:
            __fields__: ClassVar = {"x": None}
            __validators__: ClassVar = {}

        assert is_pydantic_instance(FakeV1())


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


class TestGetModelFields:
    def test_dataclass_field_order_preserved(self):
        p = Point(3.0, 4.0)
        fields = get_model_fields(p)
        assert fields == [("x", 3.0), ("y", 4.0)]

    def test_dataclass_all_fields_present(self):
        cfg = Config()
        fields = get_model_fields(cfg)
        names = [f[0] for f in fields]
        assert names == ["host", "port", "debug"]

    def test_namedtuple_fields_in_order(self):
        nt = SimpleNT(10, 20, 30)
        assert get_model_fields(nt) == [("a", 10), ("b", 20), ("c", 30)]

    def test_typed_namedtuple_fields(self):
        nt = TypedNT("hello", 5)
        assert get_model_fields(nt) == [("name", "hello"), ("value", 5)]

    def test_non_structured_returns_empty(self):
        assert get_model_fields(42) == []
        assert get_model_fields("str") == []
        assert get_model_fields([1, 2]) == []

    def test_duck_typed_pydantic_v2_fields(self):
        class FakeV2Model:
            model_fields: ClassVar = {"alpha": None, "beta": None}

            def __init__(self):
                self.alpha = 1
                self.beta = 2

        assert get_model_fields(FakeV2Model()) == [("alpha", 1), ("beta", 2)]


# ---------------------------------------------------------------------------
# VariableManager.make_variable() — named variables count & type label
# ---------------------------------------------------------------------------


class TestVariableManagerStructuredModels:
    def test_dataclass_gets_named_variables_count(self):
        mgr = VariableManager()
        var = mgr.make_variable("p", Point(1.0, 2.0))
        assert var.get("namedVariables") == 2

    def test_namedtuple_gets_named_variables_count(self):
        mgr = VariableManager()
        var = mgr.make_variable("nt", SimpleNT(1, 2, 3))
        assert var.get("namedVariables") == 3

    def test_dataclass_type_label_includes_kind(self):
        mgr = VariableManager()
        var = mgr.make_variable("p", Point(0, 0))
        assert var["type"] == "dataclass Point"

    def test_namedtuple_type_label_includes_kind(self):
        mgr = VariableManager()
        var = mgr.make_variable("nt", SimpleNT(1, 2, 3))
        assert var["type"] == "namedtuple SimpleNT"

    def test_non_structured_has_no_named_variables(self):
        mgr = VariableManager()
        var = mgr.make_variable("x", {"a": 1})
        assert "namedVariables" not in var

    def test_dataclass_is_expandable(self):
        mgr = VariableManager()
        var = mgr.make_variable("p", Point(1.0, 2.0))
        assert var["variablesReference"] != 0

    def test_namedtuple_is_expandable(self):
        mgr = VariableManager()
        var = mgr.make_variable("nt", SimpleNT(10, 20, 30))
        assert var["variablesReference"] != 0


# ---------------------------------------------------------------------------
# structured_model_label
# ---------------------------------------------------------------------------


class TestStructuredModelLabel:
    def test_dataclass_label(self):
        assert structured_model_label(Point(0, 0)) == "dataclass Point"

    def test_namedtuple_label(self):
        assert structured_model_label(SimpleNT(1, 2, 3)) == "namedtuple SimpleNT"

    def test_fallback_label_for_non_structured(self):
        assert structured_model_label(42) == "int"


# ---------------------------------------------------------------------------
# Field expansion — presentationHint.kind == "property"
# ---------------------------------------------------------------------------


def _simple_make_var(
    dbg: object, name: str, value: object, frame: object | None
) -> dict[str, object]:
    """Minimal make_variable_fn for tests (no debugger needed)."""
    mgr = VariableManager()
    return mgr.make_variable(name, value)  # type: ignore[return-value]


class TestExtractVariablesStructuredModels:
    def test_dataclass_fields_are_properties(self):
        out: list = []
        command_handler_helpers.extract_variables(
            None, out, Point(1.0, 2.0), make_variable_fn=_simple_make_var
        )
        assert {v["name"] for v in out} == {"x", "y"}
        for v in out:
            assert v["presentationHint"]["kind"] == "property", (
                f"{v['name']} kind should be 'property'"
            )

    def test_dataclass_expansion_has_no_dunder_attrs(self):
        out: list = []
        command_handler_helpers.extract_variables(
            None, out, Config(), make_variable_fn=_simple_make_var
        )
        names = {v["name"] for v in out}
        assert all(not n.startswith("_") for n in names)
        # Only declared fields should appear
        assert names == {"host", "port", "debug"}

    def test_namedtuple_fields_are_properties(self):
        out: list = []
        command_handler_helpers.extract_variables(
            None, out, TypedNT("hello", 7), make_variable_fn=_simple_make_var
        )
        names = [v["name"] for v in out]
        assert names == ["name", "value"]
        for v in out:
            assert v["presentationHint"]["kind"] == "property"

    def test_plain_tuple_still_uses_index_keys(self):
        """Plain tuples should NOT be treated as structured models."""
        out: list = []
        command_handler_helpers.extract_variables(
            None, out, (10, 20, 30), make_variable_fn=_simple_make_var
        )
        names = [v["name"] for v in out]
        assert names == ["0", "1", "2"]


class TestResolveVariablesStructuredModels:
    """Test the resolve_variables_for_reference path for structured models."""

    def test_dataclass_object_ref_fields_are_properties(self):
        mgr = VariableManager()
        p = Point(5.0, 6.0)
        ref = mgr.allocate_ref(p)
        frame_info = mgr.get_ref(ref)

        out = command_handler_helpers.resolve_variables_for_reference(
            None,
            frame_info,
            make_variable_fn=_simple_make_var,
            extract_variables_from_mapping_fn=lambda *_a, **_kw: [],
            var_ref_tuple_size=2,
        )

        names = {v["name"] for v in out}
        assert names == {"x", "y"}
        for v in out:
            assert v["presentationHint"]["kind"] == "property"

    def test_namedtuple_object_ref_fields_are_properties(self):
        mgr = VariableManager()
        nt = SimpleNT(100, 200, 300)
        ref = mgr.allocate_ref(nt)
        frame_info = mgr.get_ref(ref)

        out = command_handler_helpers.resolve_variables_for_reference(
            None,
            frame_info,
            make_variable_fn=_simple_make_var,
            extract_variables_from_mapping_fn=lambda *_a, **_kw: [],
            var_ref_tuple_size=2,
        )

        assert [v["name"] for v in out] == ["a", "b", "c"]
        for v in out:
            assert v["presentationHint"]["kind"] == "property"

    def test_plain_list_still_uses_index_keys(self):
        mgr = VariableManager()
        lst = [10, 20]
        ref = mgr.allocate_ref(lst)
        frame_info = mgr.get_ref(ref)

        out = command_handler_helpers.resolve_variables_for_reference(
            None,
            frame_info,
            make_variable_fn=_simple_make_var,
            extract_variables_from_mapping_fn=lambda *_a, **_kw: [],
            var_ref_tuple_size=2,
        )

        assert [v["name"] for v in out] == ["0", "1"]
