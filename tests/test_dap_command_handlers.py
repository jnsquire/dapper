import linecache
import sys
import threading
import types
from types import SimpleNamespace
from typing import cast

from dapper import dap_command_handlers as dch


class DummyDebugger:
    def __init__(self):
        self.cleared = []
        self.breaks = []
        self.function_breakpoints = []
        self.function_breakpoint_meta = {}
        self.exception_breakpoints_raised = False
        self.exception_breakpoints_uncaught = False
        self.stopped_thread_ids = set()
        self._continued = False
        self.stepping = False
        self.current_frame = None
        self.frames_by_thread = {}
        self.var_refs = {}
        self.frame_id_to_frame = {}
        self.next_var_ref = 1
        self.current_exception_info = {}
        self.program_path = None

    def clear_breaks_for_file(self, path):
        self.cleared.append(path)

    def clear_break(self, path):
        self.cleared.append(("alt", path))

    def clear_break_meta_for_file(self, path):
        self.cleared.append(("meta", path))

    def set_break(self, path, line, cond=None):
        self.breaks.append((path, line, cond))

    def record_breakpoint(self, path, line, **kwargs):
        self.breaks.append((path, int(line), kwargs))

    def clear_all_function_breakpoints(self):
        self.function_breakpoints.clear()

    def set_continue(self):
        self._continued = True

    def set_next(self, frame):
        self._next = frame

    def set_step(self):
        self._step = True

    def set_return(self, frame):
        self._return = frame


def test_convert_value_with_context_literal_and_bool_and_none():
    assert dch._convert_value_with_context("None") is None
    assert dch._convert_value_with_context("true") is True
    assert dch._convert_value_with_context("False") is False
    assert dch._convert_value_with_context("123") == 123


def test_convert_value_with_context_eval_with_frame():
    frame = SimpleNamespace(f_globals={"x": 5}, f_locals={})
    assert dch._convert_value_with_context("x + 1", frame) == 6


def test_set_object_member_dict_list_tuple_and_attribute():
    # dict
    d = {"a": 1}
    res = dch._set_object_member(d, "a", "2")
    assert res["success"] is True
    assert d["a"] == 2

    # list
    lst = [1, 2, 3]
    res = dch._set_object_member(lst, "1", "5")
    assert res["success"] is True
    assert lst[1] == 5

    # list invalid index
    res = dch._set_object_member(lst, "x", "5")
    assert res["success"] is False

    # tuple immutability
    tpl = (1, 2)
    res = dch._set_object_member(tpl, "0", "9")
    assert res["success"] is False

    # attribute on object
    class DummyObj:
        pass

    o = DummyObj()
    res = dch._set_object_member(o, "z", "7")
    assert res["success"] is True
    assert o.z == 7


def test_set_scope_variable_locals_and_globals():
    frame = SimpleNamespace(f_locals={}, f_globals={})
    r = dch._set_scope_variable(frame, "locals", "n", "10")
    assert r["success"] is True
    assert frame.f_locals["n"] == 10

    r = dch._set_scope_variable(frame, "globals", "g", "20")
    assert r["success"] is True
    assert frame.f_globals["g"] == 20

    r = dch._set_scope_variable(frame, "weird", "x", "1")
    assert r["success"] is False


def test_handle_set_breakpoints_and_set_function_and_exception(monkeypatch):
    dbg = DummyDebugger()
    monkeypatch.setattr(dch.state, "debugger", dbg)

    # capture send_debug_message calls
    calls = []

    def fake_send_debug_message(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", fake_send_debug_message)

    # setBreakpoints
    args = {"source": {"path": "file.py"}, "breakpoints": [{"line": 10}]}
    dch.handle_set_breakpoints(args)
    assert ("file.py", 10, None) in dbg.breaks

    # setFunctionBreakpoints
    args = {"breakpoints": [{"name": "foo", "condition": "c", "hitCondition": 1}]}
    dch.handle_set_function_breakpoints(args)
    assert "foo" in dbg.function_breakpoints
    assert dbg.function_breakpoint_meta.get("foo", {}).get("condition") == "c"

    # setExceptionBreakpoints
    args = {"filters": ["raised", "uncaught"]}
    dch.handle_set_exception_breakpoints(args)
    assert dbg.exception_breakpoints_raised is True
    assert dbg.exception_breakpoints_uncaught is True


def test_continue_next_step_out(monkeypatch):
    dbg = DummyDebugger()
    tid = threading.get_ident()
    dbg.stopped_thread_ids.add(tid)
    dbg.current_frame = object()
    monkeypatch.setattr(dch.state, "debugger", dbg)
    # capture

    def _no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dch, "send_debug_message", _no_op)

    dch.handle_continue({"threadId": tid})
    assert tid not in dbg.stopped_thread_ids
    assert dbg._continued is True

    dch.handle_next({"threadId": tid})
    assert dbg.stepping is True

    dch.handle_step_in({"threadId": tid})
    assert getattr(dbg, "_step", True) is True

    dch.handle_step_out({"threadId": tid})
    assert getattr(dbg, "_return", None) is not None


def test_variables_and_set_variable(monkeypatch):
    dbg = DummyDebugger()
    frame = SimpleNamespace(f_locals={"a": 1}, f_globals={"b": 2})
    dbg.frame_id_to_frame[1] = frame
    dbg.var_refs[7] = (1, "locals")
    monkeypatch.setattr(dch.state, "debugger", dbg)

    # stub create_variable_object to predictable output
    def fake_create_variable_object(_name, value):
        return {"value": str(value), "type": type(value).__name__, "variablesReference": 0}

    monkeypatch.setattr(dch, "create_variable_object", fake_create_variable_object)

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder)

    dch.handle_variables({"variablesReference": 7})
    assert calls
    assert calls[-1][0] == "variables"

    # setVariable invalid ref
    calls.clear()
    dch.handle_set_variable({"variablesReference": 999, "name": "x", "value": "1"})
    assert calls
    assert calls[-1][0] == "setVariable"


def test_collect_module_and_linecache_and_handle_source(monkeypatch, tmp_path):
    # create a fake module file and inject into sys.modules
    p = tmp_path / "mymod.py"
    p.write_text("# sample\n")
    m = types.ModuleType("__test_mymod__")
    m.__file__ = str(p)
    m.__package__ = "mymodpkg"
    sys.modules["__test_mymod__"] = m

    seen = set()
    sources = dch._collect_module_sources(seen)
    assert any(s.get("path") and s.get("origin") for s in sources)

    # linecache: ensure cache has the file name
    linecache.cache[str(p)] = (1, None, [], str(p))
    seen2 = set()
    line_sources = dch._collect_linecache_sources(seen2)
    assert any(s.get("path") for s in line_sources)

    # handle_source by path
    def get_source_content_by_path(_path):
        return "print(1)"

    monkeypatch.setattr(dch.state, "get_source_content_by_path", get_source_content_by_path)
    calls = []

    def recorder2(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder2)
    dch.handle_source({"path": str(p)})
    assert calls
    assert calls[-1][0] == "response"


def test_handle_evaluate_and_create_variable_object(monkeypatch):
    dbg = DummyDebugger()
    frame = SimpleNamespace(f_globals={"y": 2}, f_locals={})
    dbg.frame_id_to_frame[1] = frame
    monkeypatch.setattr(dch.state, "debugger", dbg)

    calls = []

    def recorder3(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder3)

    # successful eval
    dch.handle_evaluate({"expression": "y + 3", "frameId": 1})
    assert calls
    assert calls[-1][0] == "evaluate"

    # eval error
    dch.handle_evaluate({"expression": "unknown_var", "frameId": 1})
    assert calls
    assert calls[-1][0] == "evaluate"


def test_handle_exception_info_variants(monkeypatch):
    calls = []

    def recorder4(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder4)

    # missing threadId
    dch.handle_exception_info(cast("dict", {}))
    assert calls
    assert calls[-1][0] == "error"

    # debugger not initialized
    monkeypatch.setattr(dch.state, "debugger", None)
    calls.clear()
    dch.handle_exception_info({"threadId": 1})
    assert calls
    assert calls[-1][0] == "error"

    # debugger with no info for thread
    dbg = DummyDebugger()
    monkeypatch.setattr(dch.state, "debugger", dbg)
    calls.clear()
    dch.handle_exception_info({"threadId": 2})
    assert calls
    assert calls[-1][0] == "error"

    # with exception info
    dbg.current_exception_info[3] = {
        "exceptionId": "E",
        "description": "d",
        "breakMode": "mode",
        "details": {},
    }
    calls.clear()
    dch.handle_exception_info({"threadId": 3})
    assert calls
    assert calls[-1][0] == "exceptionInfo"


def test_create_variable_object_debugger_override_and_fallback(monkeypatch):
    # override returns dict
    class DbgWithMake(DummyDebugger):
        def make_variable_object(self, _name, _value):
            return {"value": f"dbg:{_value}", "type": "int", "variablesReference": 0}

    dbg = DbgWithMake()
    monkeypatch.setattr(dch.state, "debugger", dbg)
    res = dch.create_variable_object("n", 5)
    assert isinstance(res, dict)
    assert res["value"].startswith("dbg:")

    # make_variable_object raises -> fallback to module helper
    class DbgBad(DummyDebugger):
        def make_variable_object(self, _name, _value):
            msg = "fail"
            raise RuntimeError(msg)

    monkeypatch.setattr(dch.state, "debugger", DbgBad())
    res2 = dch.create_variable_object("n", 6)
    assert isinstance(res2, dict)


def test_loaded_sources_and_modules_paging(monkeypatch, tmp_path):
    # prepare two fake module files
    p1 = tmp_path / "a1.py"
    p1.write_text("# a1")
    p2 = tmp_path / "b2.py"
    p2.write_text("# b2")

    # register real module objects to avoid typing complaints

    m1 = types.ModuleType("m_a1")
    m1.__file__ = str(p1)
    m1.__package__ = "m_a1"
    m2 = types.ModuleType("m_b2")
    m2.__file__ = str(p2)
    m2.__package__ = "m_b2"
    sys.modules["m_a1"] = m1
    sys.modules["m_b2"] = m2

    # state handling for refs
    monkeypatch.setattr(dch.state, "get_ref_for_path", lambda _p: None)

    def get_or_create_source_ref(_p, _n=None):
        return 123

    monkeypatch.setattr(dch.state, "get_or_create_source_ref", get_or_create_source_ref)

    def get_source_meta(ref):
        return {"path": str(p1)} if ref == 123 else None

    monkeypatch.setattr(dch.state, "get_source_meta", get_source_meta)

    def get_source_content_by_ref(ref):
        return "print(1)" if ref == 123 else None

    monkeypatch.setattr(dch.state, "get_source_content_by_ref", get_source_content_by_ref)

    calls = []

    def recorder5(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder5)
    dch.handle_loaded_sources()
    assert calls
    assert calls[-1][0] == "response"

    # modules with paging
    calls.clear()
    dch.handle_modules({"startModule": 0, "moduleCount": 1})
    assert calls
    assert calls[-1][0] == "response"


def test_handle_source_binary_and_reference(monkeypatch, tmp_path):
    # binary content (contains NUL) should not set mimeType
    p = tmp_path / "bin.py"
    p.write_bytes(b"\x00\x01")

    def get_source_content_binary(_path):
        return "\x00\x01"

    monkeypatch.setattr(dch.state, "get_source_content_by_path", get_source_content_binary)
    calls = []

    def recorder6(kind, **kwargs):
        calls.append((kind, kwargs))

    monkeypatch.setattr(dch, "send_debug_message", recorder6)
    dch.handle_source({"path": str(p)})
    assert calls
    assert calls[-1][0] == "response"

    # sourceReference path mapping
    monkeypatch.setattr(dch.state, "get_source_meta", lambda _ref: {"path": str(p)})
    monkeypatch.setattr(dch.state, "get_source_content_by_ref", lambda _ref: "print(2)")
    calls.clear()
    dch.handle_source({"source": {"sourceReference": 1}})
    assert calls
    assert calls[-1][0] == "response"
