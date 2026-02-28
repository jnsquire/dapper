"""Version-compatible CodeType reconstruction for Dapper frame evaluation.

The logic here is necessarily messy because the ``CodeType`` constructor
signature has changed significantly across CPython releases (3.8 ``co_posonlyargcount``,
3.10 ``co_linetable`` / ``co_lines()``, 3.11 ``co_exceptiontable``).  We
always try the stable ``code.replace()`` API first (available since 3.8) and
only fall back to the raw ``CodeType()`` constructor when that fails.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

from dapper._frame_eval.bytecode_safety import safe_replace_code

if TYPE_CHECKING:
    import dis
    from types import CodeType


def rebuild_code_object(  # noqa: PLR0912
    original_code: CodeType,
    new_instructions: list[dis.Instruction],
) -> tuple[bool, CodeType]:
    """Rebuild *original_code* with *new_instructions* substituted in.

    Returns ``(accepted, code)`` where *accepted* is ``False`` when the safety
    validator rejects the candidate (caller should fall back to the original).
    """
    # Convert instructions back to bytecode.
    # Python 3.6+ uses a fixed 2-byte word-code format: one byte for the
    # opcode and one byte for the argument (low 8 bits).  Arguments that
    # exceed 255 are handled by EXTENDED_ARG prefix instructions, which
    # dis.get_instructions() returns as explicit Instruction objects whose
    # own arg field already contains only the relevant byte.  CACHE
    # pseudo-instructions (Python 3.11+) are also included when
    # get_instructions() is used, and they follow the same 2-byte layout.
    bytecode = bytearray()
    for instr in new_instructions:
        bytecode.append(instr.opcode)
        bytecode.append(instr.arg & 0xFF if instr.arg is not None else 0)

    # Prefer the stable replace() API (available since Python 3.8).
    # This avoids constructor-signature drift across Python versions.
    if hasattr(original_code, "replace"):
        try:
            candidate = original_code.replace(
                co_code=bytes(bytecode),
                co_stacksize=original_code.co_stacksize + 2,
            )
            return safe_replace_code(original_code, candidate)
        except Exception:
            # Fall back to legacy constructor path for compatibility.
            pass

    # Extract constants and names
    constants = list(original_code.co_consts)
    names = list(original_code.co_names)
    varnames = list(original_code.co_varnames)

    # Create new code object with appropriate parameters based on Python version
    code_args = {
        "co_argcount": original_code.co_argcount,
        "co_kwonlyargcount": original_code.co_kwonlyargcount,
        "co_nlocals": original_code.co_nlocals,
        "co_stacksize": original_code.co_stacksize + 2,  # Increase stack size for breakpoint calls
        "co_flags": original_code.co_flags,
        "co_code": bytes(bytecode),
        "co_consts": tuple(constants),
        "co_names": tuple(names),
        "co_varnames": tuple(varnames),
        "co_filename": original_code.co_filename,
        "co_name": original_code.co_name,
        "co_firstlineno": original_code.co_firstlineno,
        "co_freevars": original_code.co_freevars,
        "co_cellvars": original_code.co_cellvars,
    }

    # Handle version-specific parameters
    code_args["co_posonlyargcount"] = getattr(original_code, "co_posonlyargcount", 0)

    # For Python 3.10+, we need to handle the new code object creation
    if sys.version_info >= (3, 10):
        # Get line number information using co_lines() and convert to lnotab format
        # for backward compatibility with the code object constructor
        lnotab = bytearray()
        last_line = original_code.co_firstlineno
        last_byte = 0

        for start, _end, line in original_code.co_lines():
            if start > last_byte and line is not None:
                # Calculate the byte offset and line delta
                byte_delta = start - last_byte
                line_delta = line - last_line

                # Constants for bytecode line number table encoding
                max_byte_delta = 255
                max_line_delta = 127
                min_line_delta = -128

                # Handle multi-byte deltas
                while (
                    byte_delta > max_byte_delta
                    or line_delta > max_line_delta
                    or line_delta < min_line_delta
                ):
                    # Emit a special byte to indicate multi-byte delta
                    lnotab.extend((min(max_byte_delta, byte_delta), 0))
                    byte_delta -= min(max_byte_delta, byte_delta)
                    line_delta = max(min_line_delta, min(max_line_delta, line_delta))

                # Emit the final delta
                lnotab.extend((byte_delta, line_delta & 0xFF))
                last_byte = start
                last_line = line

        code_args["co_linetable"] = bytes(lnotab)
        # For Python 3.10+, co_lnotab is deprecated but some code might still need it
        if sys.version_info < (3, 10):
            code_args["co_lnotab"] = original_code.co_lnotab
    # For Python < 3.10, use the old co_lnotab
    elif hasattr(original_code, "co_lnotab"):
        code_args["co_lnotab"] = original_code.co_lnotab

    # Prepare common arguments for CodeType
    args = [
        code_args["co_argcount"],
        code_args.get("co_posonlyargcount", 0) if sys.version_info >= (3, 8) else 0,
        code_args["co_kwonlyargcount"],
        code_args["co_nlocals"],
        code_args["co_stacksize"],
        code_args["co_flags"],
        code_args["co_code"],
        code_args["co_consts"],
        code_args["co_names"],
        code_args["co_varnames"],
        code_args["co_filename"],
        code_args["co_name"],
        code_args.get("co_firstlineno", original_code.co_firstlineno),
        # Use co_linetable for Python 3.10+, fall back to co_lnotab for older versions
        code_args.get(
            "co_linetable" if sys.version_info >= (3, 10) else "co_lnotab",
            getattr(
                original_code,
                "co_linetable" if sys.version_info >= (3, 10) else "co_lnotab",
                b"",
            ),
        ),
        code_args.get("co_freevars", getattr(original_code, "co_freevars", ())),
        code_args.get("co_cellvars", getattr(original_code, "co_cellvars", ())),
    ]

    # Add Python 3.11+ specific arguments if available
    if sys.version_info >= (3, 11):
        args.extend(
            [
                original_code.co_positions() if hasattr(original_code, "co_positions") else None,
                original_code.co_exceptiontable
                if hasattr(original_code, "co_exceptiontable")
                else b"",
            ],
        )

    # Remove any trailing None values for older Python versions
    while args and args[-1] is None:
        args.pop()

    try:
        candidate = type(original_code)(*args)
    except Exception:
        try:
            candidate = types.CodeType(*args)
        except Exception:
            return False, original_code
    return safe_replace_code(original_code, candidate)
