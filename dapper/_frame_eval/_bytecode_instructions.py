"""Low-level bytecode instruction utilities for Dapper frame evaluation.

Provides version-compatible opcode constants, a ``dis.Instruction`` factory
that adapts to the changing ``Instruction`` named-tuple fields across Python
versions, and a helper for fetching instructions including inline CACHE
entries introduced in Python 3.11.
"""

from __future__ import annotations

import dis
import sys
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from types import CodeType

# ---------------------------------------------------------------------------
# Version-compatible opcode constants
# ---------------------------------------------------------------------------

LOAD_CONST = dis.opmap["LOAD_CONST"]
POP_TOP = dis.opmap["POP_TOP"]
JUMP_ABSOLUTE = dis.opmap.get("JUMP_ABSOLUTE", 0)
JUMP_FORWARD = dis.opmap.get("JUMP_FORWARD", 0)
SETUP_FINALLY = dis.opmap.get("SETUP_FINALLY", 0)
POP_BLOCK = dis.opmap.get("POP_BLOCK", 0)
LOAD_GLOBAL = dis.opmap["LOAD_GLOBAL"]
STORE_FAST = dis.opmap["STORE_FAST"]
LOAD_FAST = dis.opmap["LOAD_FAST"]
COMPARE_OP = dis.opmap.get("COMPARE_OP", 0)
POP_JUMP_IF_FALSE = dis.opmap.get("POP_JUMP_IF_FALSE", 0)
POP_JUMP_IF_TRUE = dis.opmap.get("POP_JUMP_IF_TRUE", 0)

# Handle different call instruction types across Python versions
if sys.version_info >= (3, 11):
    # Python 3.11+ uses different call instructions
    CALL_FUNCTION = dis.opmap.get("CALL", 0) or dis.opmap.get("CALL_FUNCTION", 0)
    CACHE = dis.opmap.get("CACHE", 0)
    RESUME = dis.opmap["RESUME"]
    LOAD_GLOBAL_CHECK = dis.opmap.get("LOAD_GLOBAL_CHECK", 0)
else:
    # Python 3.10 and earlier
    CALL_FUNCTION = dis.opmap["CALL_FUNCTION"]
    CACHE = 0
    RESUME = 0
    LOAD_GLOBAL_CHECK = 0

# Special constants for breakpoint injection
_BREAKPOINT_CONST_INDEX = -1  # Will be replaced with actual index
_DEBUGGER_CALL_CONST = "__dapper_breakpoint_check__"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_instructions(code_obj: CodeType) -> list[dis.Instruction]:
    """Return instructions for *code_obj*, including inline CACHE entries on 3.11+.

    Python 3.11 introduced per-instruction inline cache slots in ``co_code``.
    ``dis.get_instructions()`` omits them by default, so a round-trip through
    the instruction list produces a shorter byte string that Python rejects as
    malformed.  Passing ``show_caches=True`` re-includes the CACHE pseudo-
    instructions so that the reconstructed bytecode has the correct length.
    """
    if sys.version_info >= (3, 11):
        return list(dis.get_instructions(code_obj, show_caches=True))
    return list(dis.get_instructions(code_obj))


def make_instruction(
    *,
    opname: str,
    opcode: int,
    arg: int | None,
    argval: Any,
    argrepr: str,
    offset: int,
    starts_line: int | None,
    is_jump_target: bool = False,
) -> dis.Instruction:
    """Create a ``dis.Instruction``, adapting to available fields across Python versions."""
    fields = set(getattr(dis.Instruction, "_fields", ()))

    kwargs: dict[str, Any] = {
        "opname": opname,
        "opcode": opcode,
        "arg": arg,
        "argval": argval,
        "argrepr": argrepr,
        "offset": offset,
    }

    if "is_jump_target" in fields:
        kwargs["is_jump_target"] = is_jump_target

    if "starts_line" in fields:
        kwargs["starts_line"] = starts_line

    if "start_offset" in fields:
        kwargs["start_offset"] = offset

    if "line_number" in fields:
        kwargs["line_number"] = starts_line

    if "label" in fields:
        kwargs["label"] = None
    if "positions" in fields:
        kwargs["positions"] = None
    if "cache_info" in fields:
        kwargs["cache_info"] = None

    return dis.Instruction(**kwargs)
