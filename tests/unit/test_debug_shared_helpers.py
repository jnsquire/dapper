from __future__ import annotations

from dapper import debug_shared as ds
from tests.dummy_debugger import DummyDebugger


def test_format_value_str_truncation_and_error():
    long_s = "a" * 200
    out = ds._format_value_str(long_s, max_string_length=50)
    assert out.endswith("...")
    assert len(out) <= 53

    class BadRepr:
        def __repr__(self) -> str:  # pragma: no cover - exercise exception path
            msg = "bad"
            raise RuntimeError(msg)

    assert ds._format_value_str(BadRepr(), max_string_length=40) == "<Error getting value>"


def test_allocate_var_ref_basic_and_none():
    # Use the shared DummyDebugger for a fully-featured debugger-like object
    dbg = DummyDebugger()
    dbg.next_var_ref = 5
    dbg.var_refs = {}
    obj = object()
    ref = ds._allocate_var_ref(obj, dbg)
    # obj has no __dict__ but is not a sequence/dict/tuple; should return 0
    assert ref == 0

    class ObjWithDict:
        def __init__(self):
            self.x = 1

    o2 = ObjWithDict()
    ref2 = ds._allocate_var_ref(o2, dbg)
    assert ref2 == 5
    assert dbg.next_var_ref == 6
    assert dbg.var_refs[5][0] == "object"

    assert ds._allocate_var_ref(123, None) == 0


def test_detect_kind_and_attrs_for_various_types():
    kind, attrs = ds._detect_kind_and_attrs(lambda x: x)
    assert kind == "method"
    assert "hasSideEffects" in attrs

    class C:
        pass

    kind2, attrs2 = ds._detect_kind_and_attrs(C)
    # The implementation tests `callable` before `isinstance(type)`, so
    # classes are classified as 'method' (callable) by this helper.
    assert kind2 == "method"

    kind3, attrs3 = ds._detect_kind_and_attrs([1, 2, 3])
    assert kind3 == "data"

    s = "short"
    k4, a4 = ds._detect_kind_and_attrs(s)
    assert k4 == "data"

    long_s = "x" * (ds.STRING_RAW_THRESHOLD + 10)
    k5, a5 = ds._detect_kind_and_attrs(long_s)
    assert "rawString" in a5

    b = b"hello\nworld"
    k6, a6 = ds._detect_kind_and_attrs(b)
    assert k6 == "data"


def test_visibility_with_private_public_and_error():
    assert ds._visibility("_hidden") == "private"
    assert ds._visibility("visible") == "public"

    class BadStr:
        def __str__(self):
            msg = "bad"
            raise RuntimeError(msg)

    # When str() raises, function should return 'public' per implementation
    assert ds._visibility(BadStr()) == "public"


def test_detect_has_data_breakpoint_various_shapes():
    dbg = DummyDebugger()
    # Reset optional fields to control behavior
    dbg.data_watch_names = None
    dbg.data_watch_meta = None
    dbg._data_watches = None
    dbg._frame_watches = None
    # None debugger -> False
    assert ds._detect_has_data_breakpoint("a", None, None) is False

    dbg.data_watch_names = {"foo"}
    assert ds._detect_has_data_breakpoint("foo", dbg, None) is True

    dbg.data_watch_names = None
    dbg.data_watch_meta = {"bar": {}}
    assert ds._detect_has_data_breakpoint("bar", dbg, None) is True

    dbg.data_watch_meta = None
    dbg._data_watches = {":var:baz": {}, "other": {}}
    assert ds._detect_has_data_breakpoint("baz", dbg, None) is True

    dbg._data_watches = None
    dbg._frame_watches = {1: [":var:qux", "something"]}
    assert ds._detect_has_data_breakpoint("qux", dbg, fr=object()) is True

    # name not present
    assert ds._detect_has_data_breakpoint("nope", dbg, fr=object()) is False
