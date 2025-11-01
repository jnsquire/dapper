from __future__ import annotations

from typing import cast

from dapper import debug_shared as ds
from tests.dummy_debugger import DummyDebugger


def test_make_variable_object_fallback_and_var_ref_allocation():
    dbg = DummyDebugger()

    # object with __dict__ should allocate a var ref
    class Obj:
        def __init__(self):
            self.x = 1

    o = Obj()
    res = ds._make_variable_object_impl("obj", o, dbg, frame=None)
    assert isinstance(res, dict)
    ref = res["variablesReference"]
    assert isinstance(ref, int)
    if ref != 0:
        entry = dbg.var_refs.get(ref)
        assert entry is not None
        assert entry[0] == "object"

    # ensure visibility is private for names starting with underscore
    res2 = ds._make_variable_object_impl("_hidden", 5, dbg, frame=None)
    ph = cast("dict", res2["presentationHint"])
    assert ph.get("visibility") == "private"
