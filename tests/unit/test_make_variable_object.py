from __future__ import annotations

from typing import cast

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import debug_shared as ds


def test_make_variable_object_fallback_and_var_ref_allocation():
    dbg = DebuggerBDB()

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
        entry = dbg.var_manager.var_refs.get(ref)
        assert entry is not None
        assert entry[0] == "object"

    # ensure visibility is private for names starting with underscore
    res2 = ds._make_variable_object_impl("_hidden", 5, dbg, frame=None)
    ph = cast("dict", res2["presentationHint"])
    assert ph.get("visibility") == "private"
