import linecache
import types
from types import SimpleNamespace
from typing import cast

from dapper import debug_helpers as dh


def test_safe_getattr_basic_and_none_and_type_mismatch():
    class Obj:
        a = 1

    class ObjNone:
        a = None

    class ObjBad:
        def __getattr__(self, name):
            msg = "nope"
            raise RuntimeError(msg)

    assert dh.safe_getattr(Obj(), "a", 0) == 1
    assert dh.safe_getattr(ObjNone(), "a", 5) == 5
    assert dh.safe_getattr(ObjBad(), "a", 7) == 7

    # expected_type mismatch
    class ObjStr:
        a = "s"

    assert dh.safe_getattr(ObjStr(), "a", 0, expected_type=int) == 0


def test_get_wrappers_use_expected_attributes():
    def sample():
        return 1

    # function has __code__ attribute
    code = dh.get_code(sample, "__code__")
    assert isinstance(code, types.CodeType)
    # retrieving missing attributes returns default
    assert dh.get_int(sample, "missing_int", 42) == 42
    assert dh.get_str(sample, "missing_str", "x") == "x"


def test_frame_has_ast_handler_true_and_false(tmp_path):
    # create a file with a try/except covering an inner line
    content = [
        "# header\n",
        "def f():\n",
        "    try:\n",
        "        x = 1\n",
        "    except Exception:\n",
        "        x = 2\n",
        "    return x\n",
    ]
    p = tmp_path / "try_module.py"
    p.write_text("".join(content))
    linecache.clearcache()

    # choose a lineno inside the try body (the 'x = 1' line)
    target_lineno = 4
    dummy_code = cast("types.CodeType", SimpleNamespace(co_filename=str(p)))

    res = dh.frame_has_ast_handler(dummy_code, target_lineno)
    assert res is True

    # create a file without try
    content2 = ["# no try\n", "a = 1\n", "b = 2\n"]
    p2 = tmp_path / "notry.py"
    p2.write_text("".join(content2))
    linecache.clearcache()
    dummy_code2 = cast("types.CodeType", SimpleNamespace(co_filename=str(p2)))
    res2 = dh.frame_has_ast_handler(dummy_code2, 2)
    assert res2 is False


def test_frame_may_handle_exception_delegates_to_ast(tmp_path):
    # ensure that frame_may_handle_exception returns True for a frame
    # whose code filename contains a try/except that covers the lineno
    content = [
        "# header\n",
        "def g():\n",
        "    try:\n",
        "        y = 2\n",
        "    except Exception:\n",
        "        y = 3\n",
    ]
    p = tmp_path / "try2.py"
    p.write_text("".join(content))
    linecache.clearcache()

    # create a real code object compiled with the target filename so
    # get_code will accept it as a CodeType when accessed via f_code
    all_text = "".join(content)
    code_obj = compile(all_text, filename=str(p), mode="exec")
    frame_like = cast("types.FrameType", SimpleNamespace(f_code=code_obj, f_lineno=4))

    res = dh.frame_may_handle_exception(frame_like)
    assert res is True
