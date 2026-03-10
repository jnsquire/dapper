from __future__ import annotations

import importlib
import importlib.machinery
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

FRAME_EVALUATOR_MODULE = "dapper._frame_eval._frame_evaluator"
_EXTENSION_SUFFIXES = tuple(importlib.machinery.EXTENSION_SUFFIXES)


def _is_extension_origin(origin: str | None) -> bool:
    return bool(origin and origin.endswith(_EXTENSION_SUFFIXES))


def get_loaded_compiled_frame_evaluator() -> ModuleType | None:
    try:
        module = importlib.import_module(FRAME_EVALUATOR_MODULE)
    except ImportError:
        return None

    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    origin = getattr(module, "__file__", None) or getattr(spec, "origin", None)

    if isinstance(loader, importlib.machinery.ExtensionFileLoader):
        return module
    if _is_extension_origin(origin):
        return module
    return None


def has_loaded_compiled_frame_evaluator() -> bool:
    return get_loaded_compiled_frame_evaluator() is not None


def compiled_frame_evaluator_expected() -> bool:
    version_tuple = sys.version_info[:2]
    return version_tuple in {(3, 11), (3, 12)}


def assert_loaded_compiled_frame_evaluator() -> ModuleType:
    module = get_loaded_compiled_frame_evaluator()
    if module is not None:
        return module

    imported = importlib.import_module(FRAME_EVALUATOR_MODULE)
    spec = getattr(imported, "__spec__", None)
    origin = getattr(imported, "__file__", None) or getattr(spec, "origin", None)
    loader = type(getattr(spec, "loader", None)).__name__ if spec is not None else None
    message = (
        "Frame-eval module imported, but the loaded module is not the compiled Cython "
        f"extension. origin={origin!r}, loader={loader!r}"
    )
    raise AssertionError(message)
