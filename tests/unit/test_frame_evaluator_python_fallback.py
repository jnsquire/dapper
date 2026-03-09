from __future__ import annotations

import gc
import importlib.util
from pathlib import Path
from types import CodeType
import weakref


def _load_python_fallback_module():
    module_path = Path(__file__).resolve().parents[2] / "dapper" / "_frame_eval" / "_frame_evaluator.py"
    spec = importlib.util.spec_from_file_location("dapper_frame_evaluator_python_fallback_test", module_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_function_code(name: str) -> CodeType:
    compiled = compile(f"def {name}():\n    return 1\n", f"<{name}>", "exec")
    return next(
        const
        for const in compiled.co_consts
        if isinstance(const, CodeType) and const.co_name == name
    )


def test_python_fallback_code_extra_metadata_does_not_keep_code_objects_alive() -> None:
    module = _load_python_fallback_module()

    original_code = _make_function_code("original")
    code_ref = weakref.ref(original_code)

    assert module._store_code_extra_metadata(original_code, {"breakpoint_lines": {2}}) is True
    assert module._get_code_extra_metadata(original_code) == {"breakpoint_lines": {2}}
    assert len(module._code_extra_fallback) == 1

    del original_code
    gc.collect()

    assert code_ref() is None
    assert len(module._code_extra_fallback) == 0
