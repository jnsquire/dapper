"""
Helpers and utilities for debug launcher."""

from __future__ import annotations

import ast
import dis
from itertools import chain
import linecache
import types
from typing import Any
from typing import TypeVar
from typing import cast

T = TypeVar("T")


def safe_getattr(
    obj: Any,
    name: str,
    default: T,
    expected_type: type[T] | None = None,
) -> T:
    try:
        val = getattr(obj, name)
    except Exception:
        return default
    if expected_type is not None and not isinstance(val, expected_type):
        return default
    return cast("T", val) if val is not None else default


def get_code(obj: Any, name: str, default: types.CodeType | None = None) -> types.CodeType | None:
    return safe_getattr(obj, name, default, types.CodeType)


def get_int(obj: Any, name: str, default: int | None = None) -> int | None:
    return safe_getattr(obj, name, default, int)


def get_str(obj: Any, name: str, default: str | None = None) -> str | None:
    return safe_getattr(obj, name, default, str)


def frame_may_handle_exception(f: types.FrameType) -> bool | None:
    code = get_code(f, "f_code", None)
    lineno = get_int(f, "f_lineno", None)
    res = frame_has_exception_table_handler(code, lineno)
    if res is None:
        res = frame_has_ast_handler(code, lineno)
    return res


def frame_has_exception_table_handler(
    code: types.CodeType | None,
    lineno: int | None,
) -> bool | None:
    result: bool | None = None
    try:
        ex_table = getattr(code, "co_exceptiontable", None)
        unpack = getattr(dis, "_unpack_exception_table", None)
        if ex_table and unpack is not None:
            try:
                entries = unpack(ex_table)
            except Exception:
                entries = None
            line_to_offset: dict[int, int] = {}
            if isinstance(code, types.CodeType):
                for offset, ln in dis.findlinestarts(code):
                    line_to_offset.setdefault(ln, offset)
            if entries is not None and lineno is not None and lineno in line_to_offset:
                offset = line_to_offset[lineno]
                for start, end, _target, _depth, _kind in entries:
                    if start <= offset < end:
                        result = True
                        break
                if result is None:
                    result = False
    except Exception:
        result = None
    return result


def frame_has_ast_handler(code: types.CodeType | None, lineno: int | None) -> bool | None:
    """Determines if the given code object has an AST handler for exceptions
    at the specified line number.

    Returns:
        True if an exception handler is present,
        False if not,
        None if the information cannot be determined.
    """
    try:
        filename = get_str(code, "co_filename", None)
        source_lines = linecache.getlines(filename) if filename else []
        if not source_lines:
            return None
        all_lines = "".join(source_lines)
        tree = ast.parse(all_lines, filename=filename or "<unknown>")
        result = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            start = get_int(node, "lineno", None)
            if start is None:
                continue
            end = get_int(node, "end_lineno", None)
            if end is None:
                nums = filter(
                    None,
                    (
                        get_int(n, "lineno", start)
                        for n in chain(node.body, node.handlers, node.orelse, node.finalbody)
                    ),
                )
                end = max(nums) if nums else start
            if lineno is not None and start <= lineno <= end and node.handlers:
                result = True
                break
        if result is None:
            result = False
    except Exception:
        result = None
    return result
