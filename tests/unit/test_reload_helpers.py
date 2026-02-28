"""Unit tests for dapper.shared.reload_helpers."""

from __future__ import annotations

import importlib.machinery
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.shared.reload_helpers import _extension_suffixes
from dapper.shared.reload_helpers import _get_all_frames
from dapper.shared.reload_helpers import _is_closure
from dapper.shared.reload_helpers import _maybe_update_frame_code
from dapper.shared.reload_helpers import _replacement_for_value
from dapper.shared.reload_helpers import _try_invalidate_frame_eval
from dapper.shared.reload_helpers import build_rebind_map
from dapper.shared.reload_helpers import check_reloadable_source
from dapper.shared.reload_helpers import collect_module_functions
from dapper.shared.reload_helpers import delete_stale_pyc
from dapper.shared.reload_helpers import is_code_compatible
from dapper.shared.reload_helpers import perform_reload
from dapper.shared.reload_helpers import rebind_stack_frames
from dapper.shared.reload_helpers import resolve_module_for_path

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_fn(src: str, name: str = "fn") -> types.FunctionType:
    """Compile a tiny function and return it."""
    ns: dict = {}
    exec(compile(src, f"<test:{name}>", "exec"), ns)
    return ns[name]


def _simple_fn() -> int:
    return 42


def _closure_factory():
    x = 1

    def inner():
        return x

    return inner


# ---------------------------------------------------------------------------
# _extension_suffixes
# ---------------------------------------------------------------------------


class TestExtensionSuffixes:
    def test_returns_tuple(self):
        result = _extension_suffixes()
        assert isinstance(result, tuple)

    def test_contains_so(self):
        # .so is a hard-coded default; should always be present
        assert ".so" in _extension_suffixes()

    def test_deduplicates_with_importlib_suffixes(self):
        suffixes = _extension_suffixes()
        assert len(suffixes) == len(set(suffixes))

    def test_nonempty(self):
        assert len(_extension_suffixes()) > 0

    def test_fallback_when_attribute_missing(self):
        im = importlib.machinery
        original = getattr(im, "EXTENSION_SUFFIXES", None)
        try:
            im.EXTENSION_SUFFIXES = None  # type: ignore[attr-defined]
            result = _extension_suffixes()
            assert ".so" in result
        finally:
            if original is None:
                del im.EXTENSION_SUFFIXES  # type: ignore[attr-defined]
            else:
                im.EXTENSION_SUFFIXES = original


# ---------------------------------------------------------------------------
# check_reloadable_source
# ---------------------------------------------------------------------------


class TestCheckReloadableSource:
    def test_accepts_py(self, tmp_path):
        f = tmp_path / "module.py"
        f.touch()
        check_reloadable_source(f)  # should not raise

    def test_accepts_pyw(self, tmp_path):
        f = tmp_path / "module.pyw"
        f.touch()
        check_reloadable_source(f)  # should not raise

    def test_rejects_non_py(self, tmp_path):
        f = tmp_path / "data.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a Python source file"):
            check_reloadable_source(f)

    def test_rejects_c_extension_so(self, tmp_path):
        f = tmp_path / "mymodule.so"
        f.touch()
        with pytest.raises(ValueError, match="Cannot reload C extension"):
            check_reloadable_source(f)


# ---------------------------------------------------------------------------
# resolve_module_for_path
# ---------------------------------------------------------------------------


class TestResolveModuleForPath:
    def test_finds_loaded_module(self, tmp_path):
        mod_file = tmp_path / "mymod.py"
        mod_file.write_text("x = 1\n")
        fake_mod = types.ModuleType("mymod")
        fake_mod.__file__ = str(mod_file)
        with patch.dict(sys.modules, {"mymod": fake_mod}):
            name, mod = resolve_module_for_path(str(mod_file))
        assert name == "mymod"
        assert mod is fake_mod

    def test_handles_pyc_file_attribute(self, tmp_path):
        mod_file = tmp_path / "mymod.py"
        mod_file.write_text("x = 1\n")
        fake_mod = types.ModuleType("mymod")
        # __file__ points at .pyc but should still match the .py path
        fake_mod.__file__ = str(mod_file) + "c"  # .pyc
        with patch.dict(sys.modules, {"mymod": fake_mod}):
            name, _mod = resolve_module_for_path(str(mod_file))
        assert name == "mymod"

    def test_raises_when_not_found(self, tmp_path):
        f = tmp_path / "notloaded.py"
        f.write_text("x = 1\n")
        with pytest.raises(ValueError, match="Module not loaded"):
            resolve_module_for_path(str(f))

    def test_skips_module_without_file(self, tmp_path):
        f = tmp_path / "nativeMod.py"
        f.write_text("pass\n")
        fake_mod = types.ModuleType("native")
        # no __file__
        with (
            patch.dict(sys.modules, {"native": fake_mod}),
            pytest.raises(ValueError, match="Module not loaded"),
        ):
            resolve_module_for_path(str(f))


# ---------------------------------------------------------------------------
# collect_module_functions
# ---------------------------------------------------------------------------


class TestCollectModuleFunctions:
    def test_returns_only_functions(self):
        mod = types.ModuleType("m")
        mod.fn = _simple_fn  # type: ignore[attr-defined]
        mod.not_fn = 42  # type: ignore[attr-defined]
        result = collect_module_functions(mod)
        assert "fn" in result
        assert "not_fn" not in result

    def test_returns_empty_for_empty_module(self):
        mod = types.ModuleType("empty")
        assert collect_module_functions(mod) == {}

    def test_handles_module_without_dict(self):
        # Passing None-ish object: co_filename etc. absent
        result = collect_module_functions(None)  # type: ignore[arg-type]
        assert result == {}

    def test_handles_non_dict_dict_attribute(self):
        class FakeModule:
            __dict__ = "not-a-dict"  # type: ignore[assignment]

        assert collect_module_functions(FakeModule()) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_rebind_map
# ---------------------------------------------------------------------------


class TestBuildRebindMap:
    def test_maps_by_function_identity(self):
        def old_fn():
            return 1

        def new_fn():
            return 2

        rebind = build_rebind_map({"f": old_fn}, {"f": new_fn})
        assert rebind[id(old_fn)] is new_fn

    def test_maps_by_code_identity(self):
        def old_fn():
            return 1

        def new_fn():
            return 2

        rebind = build_rebind_map({"f": old_fn}, {"f": new_fn})
        assert rebind[id(old_fn.__code__)] is new_fn

    def test_skips_unknown_names(self):
        def old_fn():
            return 1

        rebind = build_rebind_map({"f": old_fn}, {})
        assert id(old_fn) not in rebind

    def test_empty_inputs(self):
        assert build_rebind_map({}, {}) == {}


# ---------------------------------------------------------------------------
# is_code_compatible
# ---------------------------------------------------------------------------


class TestIsCodeCompatible:
    def _code(self, src: str) -> types.CodeType:
        ns: dict = {}
        exec(compile(src, "<test>", "exec"), ns)
        # Return the first code constant that is itself a CodeType
        top_code = compile(src, "<test>", "exec")
        for c in top_code.co_consts:
            if isinstance(c, types.CodeType):
                return c
        return top_code

    def test_identical_functions_compatible(self):
        src = "def f(a, b):\n    return a + b\n"
        code = self._code(src)
        ok, reason = is_code_compatible(code, code)
        assert ok is True
        assert reason == ""

    def test_different_argcount_incompatible(self):
        c1 = self._code("def f(a):\n    return a\n")
        c2 = self._code("def f(a, b):\n    return a\n")
        ok, reason = is_code_compatible(c1, c2)
        assert ok is False
        assert "co_argcount" in reason

    def test_different_varnames_length_incompatible(self):
        c1 = self._code("def f(a):\n    x = 1\n    return x\n")
        c2 = self._code("def f(a):\n    x = 1\n    y = 2\n    return x + y\n")
        ok, reason = is_code_compatible(c1, c2)
        assert ok is False
        # Either co_nlocals or co_varnames length would catch this
        assert "co_nlocals" in reason or "co_varnames" in reason


# ---------------------------------------------------------------------------
# _is_closure
# ---------------------------------------------------------------------------


class TestIsClosure:
    def test_plain_function_not_closure(self):
        def f():
            return 1

        assert _is_closure(f) is False

    def test_closure_detected(self):
        inner = _closure_factory()
        assert _is_closure(inner) is True


# ---------------------------------------------------------------------------
# _replacement_for_value
# ---------------------------------------------------------------------------


class TestReplacementForValue:
    def test_replaces_function_by_identity(self):
        def old():
            pass

        def new():
            pass

        rebind = {id(old): new}
        assert _replacement_for_value(old, rebind) is new

    def test_replaces_function_by_code_identity(self):
        def old():
            pass

        def new():
            pass

        rebind = {id(old.__code__): new}
        assert _replacement_for_value(old, rebind) is new

    def test_replaces_bound_method_by_function_identity(self):
        class Obj:
            def method(self):
                pass

        obj = Obj()
        old_fn = obj.method.__func__

        def new_fn(self):
            pass

        rebind = {id(old_fn): new_fn}
        result = _replacement_for_value(obj.method, rebind)
        assert isinstance(result, types.MethodType)
        assert result.__func__ is new_fn
        assert result.__self__ is obj

    def test_returns_none_for_unknown_value(self):
        assert _replacement_for_value(42, {}) is None  # type: ignore[arg-type]

    def test_returns_none_when_not_in_map(self):
        def f():
            pass

        assert _replacement_for_value(f, {}) is None


# ---------------------------------------------------------------------------
# _maybe_update_frame_code
# ---------------------------------------------------------------------------


class TestMaybeUpdateFrameCode:
    def _make_frame_mock(self, code: types.CodeType) -> MagicMock:
        frame = MagicMock(spec=types.FrameType)
        frame.f_code = code
        return frame

    def test_returns_false_when_disabled(self):
        warnings: list[str] = []
        frame = self._make_frame_mock(compile("pass", "<t>", "exec"))
        assert _maybe_update_frame_code(frame, {}, warnings, update_frame_code=False) is False

    def test_returns_false_when_no_replacement(self):
        warnings: list[str] = []
        code = compile("pass", "<t>", "exec")
        frame = self._make_frame_mock(code)
        assert _maybe_update_frame_code(frame, {}, warnings, update_frame_code=True) is False

    def test_skips_closure_with_warning(self):
        def outer():
            x = 1

            def inner():
                return x

            return inner

        inner = outer()
        old_code = inner.__code__

        warnings: list[str] = []
        frame = self._make_frame_mock(old_code)
        rebind_map = {id(old_code): inner}  # inner IS a closure
        result = _maybe_update_frame_code(frame, rebind_map, warnings, update_frame_code=True)
        assert result is False
        assert any("Closure" in w or "closure" in w for w in warnings)

    def test_skips_incompatible_code_with_warning(self):
        def f1(a):
            return a

        def f2(a, b):
            return a + b

        old_code = f1.__code__
        # make f2 the replacement for f1's code
        rebind_map = {id(old_code): f2}
        warnings: list[str] = []
        frame = self._make_frame_mock(old_code)
        result = _maybe_update_frame_code(frame, rebind_map, warnings, update_frame_code=True)
        assert result is False
        assert warnings  # incompatibility warning emitted


# ---------------------------------------------------------------------------
# rebind_stack_frames
# ---------------------------------------------------------------------------


class TestRebindStackFrames:
    def test_empty_rebind_map_returns_zeros(self):
        result = rebind_stack_frames([], {}, module_name="m", update_frame_code=False)
        assert result["reboundFrames"] == 0
        assert result["updatedFrameCodes"] == 0
        assert result["warnings"] == []

    def test_skips_closure_locals_with_warning(self):
        inner = _closure_factory()

        def old_fn():
            return 1

        def new_fn():
            return 2

        rebind_map = {id(inner): new_fn, id(inner.__code__): new_fn}

        frame = MagicMock(spec=types.FrameType)
        frame.f_code = compile("pass", "<t>", "exec")
        frame.f_locals = {"fn": inner}

        result = rebind_stack_frames(
            [frame],
            rebind_map,
            module_name=getattr(inner, "__module__", __name__),
            update_frame_code=False,
        )
        # The closure skip warning should be present
        assert any("closure" in w.lower() or "Closure" in w for w in result["warnings"])

    def test_rebinds_plain_function_local(self):
        def old_fn():
            return 1

        def new_fn():
            return 2

        rebind_map = {id(old_fn): new_fn, id(old_fn.__code__): new_fn}

        f_locals_dict = {"fn": old_fn}
        frame = MagicMock(spec=types.FrameType)
        frame.f_code = compile("pass", "<t>", "exec")
        frame.f_locals = f_locals_dict

        result = rebind_stack_frames(
            [frame],
            rebind_map,
            module_name="unrelated_module",
            update_frame_code=False,
        )
        assert result["reboundFrames"] == 1
        assert f_locals_dict["fn"] is new_fn

    def test_result_typeddict_structure(self):
        result = rebind_stack_frames([], {}, module_name="m", update_frame_code=False)
        assert set(result.keys()) == {"reboundFrames", "updatedFrameCodes", "warnings"}


# ---------------------------------------------------------------------------
# delete_stale_pyc
# ---------------------------------------------------------------------------


class TestDeleteStalePyc:
    def test_returns_empty_when_no_pycache(self, tmp_path):
        src = tmp_path / "mod.py"
        src.touch()
        warnings = delete_stale_pyc(src)
        assert warnings == []

    def test_deletes_matching_pyc_files(self, tmp_path):
        src = tmp_path / "mod.py"
        src.touch()
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        pyc = pycache / "mod.cpython-39.pyc"
        pyc.write_bytes(b"fake")
        warnings = delete_stale_pyc(src)
        assert warnings == []
        assert not pyc.exists()

    def test_unrelated_pyc_not_deleted(self, tmp_path):
        src = tmp_path / "mod.py"
        src.touch()
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        other = pycache / "other.cpython-39.pyc"
        other.write_bytes(b"fake")
        delete_stale_pyc(src)
        assert other.exists()

    def test_appends_warning_on_deletion_failure(self, tmp_path):
        src = tmp_path / "mod.py"
        src.touch()
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        pyc = pycache / "mod.cpython-39.pyc"
        pyc.write_bytes(b"fake")

        with patch.object(Path, "unlink", side_effect=OSError("locked")):
            warnings = delete_stale_pyc(src)

        assert any("Failed to delete" in w for w in warnings)


# ---------------------------------------------------------------------------
# _try_invalidate_frame_eval
# ---------------------------------------------------------------------------


class TestTryInvalidateFrameEval:
    def test_no_warning_on_success(self):
        mock_fn = MagicMock()
        with patch(
            "dapper.shared.reload_helpers._try_invalidate_frame_eval",
            side_effect=lambda path, w: None,
        ):
            # just verify the real signature doesn't blow up when module available
            pass

        warnings: list[str] = []
        with patch.dict(
            sys.modules,
            {"dapper._frame_eval.cache_manager": MagicMock(invalidate_breakpoints=mock_fn)},
        ):
            _try_invalidate_frame_eval("/some/path.py", warnings)
        assert warnings == []

    def test_appends_warning_on_import_error(self):
        warnings: list[str] = []
        with patch(
            "builtins.__import__",
            side_effect=ImportError("no frame eval"),
        ):
            _try_invalidate_frame_eval("/some/path.py", warnings)
        assert any("cache invalidation failed" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# _get_all_frames
# ---------------------------------------------------------------------------


class TestGetAllFrames:
    def test_returns_list_of_frames(self):
        frames = _get_all_frames()
        assert isinstance(frames, list)
        assert all(isinstance(f, types.FrameType) for f in frames)

    def test_includes_current_frame(self):
        current = sys._getframe()
        frames = _get_all_frames()
        frame_ids = {id(f) for f in frames}
        # At minimum our own frame or its caller should appear
        assert any(id(current) == fid or id(current.f_back) == fid for fid in frame_ids)

    def test_no_duplicates(self):
        frames = _get_all_frames()
        assert len(frames) == len({id(f) for f in frames})


# ---------------------------------------------------------------------------
# perform_reload (integration of all helpers)
# ---------------------------------------------------------------------------


class TestPerformReload:
    def _write_module(self, tmp_path: Path, name: str, content: str) -> Path:
        f = tmp_path / f"{name}.py"
        f.write_text(content)
        return f

    def test_raises_for_nonexistent_path(self, tmp_path):
        with pytest.raises(OSError, match=r"missing\.py"):
            perform_reload(str(tmp_path / "missing.py"), None)

    def test_raises_for_c_extension(self, tmp_path):
        f = tmp_path / "ext.so"
        f.touch()
        with pytest.raises(ValueError, match="Cannot reload C extension"):
            perform_reload(str(f), None)

    def test_raises_when_module_not_loaded(self, tmp_path):
        f = self._write_module(tmp_path, "notloaded", "x = 1\n")
        with pytest.raises(ValueError, match="Module not loaded"):
            perform_reload(str(f), None)

    def test_successful_reload(self, tmp_path):
        f = self._write_module(tmp_path, "live_mod", "def fn():\n    return 1\n")
        mod = types.ModuleType("live_mod")
        mod.__file__ = str(f)
        fn = _make_fn("def fn():\n    return 1\n")
        mod.fn = fn  # type: ignore[attr-defined]

        with (
            patch.dict(sys.modules, {"live_mod": mod}),
            patch("dapper.shared.reload_helpers.importlib.reload", return_value=mod),
        ):
            result = perform_reload(str(f), None, get_frames_fn=list)

        assert result["reloadedModule"] == "live_mod"
        assert isinstance(result["reboundFrames"], int)
        assert isinstance(result["updatedFrameCodes"], int)
        assert isinstance(result["warnings"], list)

    def test_options_disable_pyc_invalidation(self, tmp_path):
        f = self._write_module(tmp_path, "optmod", "x = 1\n")
        mod = types.ModuleType("optmod")
        mod.__file__ = str(f)

        with (
            patch.dict(sys.modules, {"optmod": mod}),
            patch("dapper.shared.reload_helpers.importlib.reload", return_value=mod),
            patch("dapper.shared.reload_helpers.delete_stale_pyc") as mock_del,
        ):
            perform_reload(
                str(f),
                {"invalidatePycache": False},  # type: ignore[arg-type]
                get_frames_fn=list,
            )

        mock_del.assert_not_called()

    def test_result_has_required_keys(self, tmp_path):
        f = self._write_module(tmp_path, "keymod", "x = 1\n")
        mod = types.ModuleType("keymod")
        mod.__file__ = str(f)

        with (
            patch.dict(sys.modules, {"keymod": mod}),
            patch("dapper.shared.reload_helpers.importlib.reload", return_value=mod),
        ):
            result = perform_reload(str(f), None, get_frames_fn=list)

        assert set(result.keys()) == {
            "reloadedModule",
            "reboundFrames",
            "updatedFrameCodes",
            "warnings",
        }
