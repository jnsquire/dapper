from dapper.debug_shared import make_variable_object
from dapper.debugger_bdb import DebuggerBDB


def test_variable_has_data_breakpoint_for_watched_name():
    dbg = DebuggerBDB()
    # Register a data watch for variable 'x'
    dbg.register_data_watches(["x"])

    var = make_variable_object("x", 123, dbg=dbg)

    attrs = var.get("presentationHint", {}).get("attributes", [])
    assert "hasDataBreakpoint" in attrs
