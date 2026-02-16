import textwrap

from dapper.core import debug_helpers as dh


def test_safe_getattr_and_wrappers():
    class Obj:
        x = 1

        @property
        def bad(self):
            raise RuntimeError("boom")

        f_code = (lambda: None).__code__
        val_int = 42
        val_str = "hello"

    o = Obj()

    # basic getattr
    assert dh.safe_getattr(o, "x", 0) == 1

    # getattr that raises should return default
    assert dh.safe_getattr(o, "bad", "def") == "def"

    # missing attribute returns default
    assert dh.safe_getattr(o, "missing", "d") == "d"

    # expected_type mismatch returns default
    assert dh.safe_getattr(o, "x", "d", expected_type=str) == "d"

    # wrappers
    assert dh.get_code(o, "f_code") is o.f_code
    assert dh.get_int(o, "val_int") == 42
    assert dh.get_str(o, "val_str") == "hello"


def test_frame_has_ast_handler_positive_and_negative(tmp_path):
    # Create a temporary python source file with a try/except block
    src = textwrap.dedent(
        """
        def foo():
            x = 0
            try:
                a = 1
            except Exception:
                a = 2

        def bar():
            pass
        """
    )

    p = tmp_path / "mod_with_try.py"
    p.write_text(src)

    # Compile the source with the filename pointing to the temp file
    code = compile(src, str(p), "exec")

    # Line 4 (1-based) contains the assignment inside the try block -> should detect handler
    assert dh.frame_has_ast_handler(code, 4) is True

    # Line 2 is outside the try/except -> should be False
    assert dh.frame_has_ast_handler(code, 2) is False


def test_frame_has_ast_handler_returns_none_for_missing_source():
    # Compile code with a filename that does not exist on disk
    src = "x = 1\n"
    code = compile(src, "nonexistent_file_for_test.py", "exec")

    # linecache will be empty for this filename -> function should return None
    assert dh.frame_has_ast_handler(code, 1) is None


from pathlib import Path
import types
from typing import Any
from typing import cast


def test_safe_getattr_basic_and_type_checks():
    class A:
        x = 1

    assert dh.safe_getattr(A(), "x", 0) == 1

    class B:
        def __getattr__(self, name):
            msg = "boom"
            raise RuntimeError(msg)

    # getattr raises -> return default
    assert dh.safe_getattr(B(), "missing", "def") == "def"

    class C:
        x = "s"

    # expected_type mismatch -> default
    assert dh.safe_getattr(C(), "x", 0, expected_type=int) == 0

    class D:
        x = None

    # None should be treated as missing and default returned
    assert dh.safe_getattr(D(), "x", "d") == "d"


def test_get_wrappers():
    code = compile("pass", "<test>", "exec")
    ns = types.SimpleNamespace(f_code=code, f_lineno=42)

    assert dh.get_code(ns, "f_code") is code
    assert dh.get_int(ns, "f_lineno") == 42

    fn = types.SimpleNamespace(co_filename="/f.py")
    assert dh.get_str(fn, "co_filename") == "/f.py"


def test_frame_has_ast_handler_true_false(tmp_path):
    # Create a temporary python file with a try/except covering specific lines
    src_lines = [
        "# test module\n",
        "def foo():\n",
        "    try:\n",
        "        x = 1\n",
        "    except Exception:\n",
        "        x = 2\n",
        "    y = 3\n",
    ]
    src = "".join(src_lines)
    fname = tmp_path / "mod_with_try.py"
    fname.write_text(src)

    # compile with filename set to the temporary file so AST detection reads it
    code = compile(src, str(fname), "exec")

    # line 4 is inside the try block -> should detect handler True
    assert dh.frame_has_ast_handler(code, 4) is True

    # line 7 is outside try -> should be False
    assert dh.frame_has_ast_handler(code, 7) is False


def test_frame_has_ast_handler_missing_file():
    # Compile code with a filename that does not exist -> linecache yields no lines
    src = "def foo():\n    pass\n"
    fake_fname = Path.cwd() / "nonexistent_for_test_12345.py"
    code = compile(src, fake_fname, "exec")

    # file missing -> cannot determine -> returns None
    assert dh.frame_has_ast_handler(code, 2) is None


def test_frame_may_handle_exception_uses_ast(tmp_path):
    # Verify frame_may_handle_exception falls back to AST when exception table is absent
    src_lines = [
        "def foo():\n",
        "    try:\n",
        "        a = 1\n",
        "    except Exception:\n",
        "        a = 2\n",
    ]
    src = "".join(src_lines)
    fname = tmp_path / "mod_try2.py"
    fname.write_text(src)

    code = compile(src, str(fname), "exec")

    # craft a simple frame-like object with f_code and f_lineno
    frame_like = types.SimpleNamespace(f_code=code, f_lineno=3)

    assert dh.frame_may_handle_exception(cast("Any", frame_like)) is True
