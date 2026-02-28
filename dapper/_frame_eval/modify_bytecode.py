"""Bytecode modification utilities for Dapper frame evaluation.

This module provides safe bytecode manipulation capabilities to inject
breakpoints directly into Python code objects for optimized debugging.

Lower-level helpers live in neighbouring modules:

* :mod:`dapper._frame_eval._bytecode_instructions` — opcode constants,
  ``make_instruction()``, ``get_instructions()``
* :mod:`dapper._frame_eval._code_object_builder` — ``rebuild_code_object()``
"""

from __future__ import annotations

import dis
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict

from dapper._frame_eval._bytecode_instructions import CALL_FUNCTION
from dapper._frame_eval._bytecode_instructions import LOAD_CONST
from dapper._frame_eval._bytecode_instructions import POP_TOP
from dapper._frame_eval._bytecode_instructions import get_instructions
from dapper._frame_eval._bytecode_instructions import make_instruction
from dapper._frame_eval._code_object_builder import rebuild_code_object
from dapper._frame_eval.telemetry import telemetry

if TYPE_CHECKING:
    from types import CodeType


class BytecodeInfo(TypedDict):
    """Type definition for bytecode information dictionary.

    Attributes:
        instruction_count: Number of instructions in the bytecode
        has_breakpoints: Whether the bytecode contains breakpoint sequences
        stack_size: Maximum stack size required by the code
        flags: Code object flags (co_flags)
        first_lineno: First line number in the source code
        filename: Name of the source file
        name: Name of the code object
        constants_count: Number of constants in the code object
        names_count: Number of names in the code object
        varnames_count: Number of local variable names in the code object
    """

    instruction_count: int
    has_breakpoints: bool
    stack_size: int
    flags: int
    first_lineno: int
    filename: str
    name: str
    constants_count: int
    names_count: int
    varnames_count: int


class BytecodeErrorInfo(TypedDict):
    """Type definition for bytecode error information.

    Used when bytecode analysis fails.

    Attributes:
        error: Error message
        filename: Name of the source file if available, otherwise 'unknown'
        name: Name of the code object if available, otherwise 'unknown'

    """

    error: str
    filename: str
    name: str



class BytecodeModifier:
    """Advanced bytecode modification system for frame evaluation."""

    def __init__(self):
        self.breakpoint_counter = 0
        self.modified_code_objects = {}
        self.optimization_enabled = True

    def inject_breakpoints(
        self,
        code_obj: CodeType,
        breakpoint_lines: set[int],
        debug_mode: bool = False,
    ) -> tuple[bool, CodeType]:
        """Inject breakpoints into a code object at specified lines.

        Args:
            code_obj: The original code object to modify
            breakpoint_lines: Set of line numbers with breakpoints
            debug_mode: Enable debug mode for verbose logging

        Returns:
            tuple: (success, modified_code_obj)

        """
        if not breakpoint_lines:
            return True, code_obj

        try:
            # Create a cache key for this code object
            cache_key = self._get_cache_key(code_obj, breakpoint_lines)

            # Check if we already have a modified version
            if cache_key in self.modified_code_objects:
                return True, self.modified_code_objects[cache_key]

            # Get original instructions (including CACHE entries on 3.11+)
            instructions = get_instructions(code_obj)

            # Find injection points
            injection_points = self._find_injection_points(instructions, breakpoint_lines)

            if not injection_points:
                # No valid injection points found
                return True, code_obj

            # Create new instruction list with breakpoints
            new_instructions = self._create_breakpoint_instructions(instructions, injection_points)

            # Rebuild code object — validated by the safety layer
            accepted, modified_code = rebuild_code_object(code_obj, new_instructions)

            if not accepted:
                # Validation failure already recorded by _rebuild_code_object.
                return False, code_obj

            # Cache the result
            self.modified_code_objects[cache_key] = modified_code
        except Exception as e:
            if debug_mode:
                print(f"Error injecting breakpoints: {e}")
            telemetry.record_bytecode_injection_failed(
                filename=getattr(code_obj, "co_filename", "unknown"),
                name=getattr(code_obj, "co_name", "unknown"),
            )
            return False, code_obj
        else:
            return True, modified_code

    def create_breakpoint_wrapper_code(self, line: int) -> CodeType:
        """Create a code object that serves as a breakpoint wrapper.

        Args:
            line: The line number for the breakpoint

        Returns:
            CodeType: Compiled wrapper code object

        """
        wrapper_source = f'''
def __dapper_breakpoint_wrapper_{line}():
    """Breakpoint wrapper for line {line}."""
    try:
        # Get the current frame
        import sys
        frame = sys._getframe(1)

        # Check if we should stop at this line
        filename = frame.f_code.co_filename
        lineno = {line}

        # Call the debugger's breakpoint check
        if hasattr(sys, '_pydevd_frame_eval'):
            debugger_info = sys._pydevd_frame_eval
            if 'check_breakpoint' in debugger_info:
                should_stop = debugger_info['check_breakpoint'](filename, lineno, frame)
                if should_stop:
                    debugger_info['stop_at_frame'](frame)
                    return

        # Fallback: check for trace function
        if hasattr(sys, 'trace_function') and sys.trace_function:
            sys.trace_function(frame, 'line', None)

    except Exception:
        # Silently ignore errors to avoid breaking execution
        pass

__dapper_breakpoint_wrapper_{line}()
'''

        # Compile the wrapper
        return compile(wrapper_source, f"<dapper_breakpoint_wrapper_{line}>", "exec")

    def optimize_code_object(self, code_obj: CodeType) -> CodeType:
        """Optimize a code object for better frame evaluation performance.

        Args:
            code_obj: The code object to optimize

        Returns:
            CodeType: Optimized code object

        """
        if not self.optimization_enabled:
            return code_obj

        try:
            instructions = get_instructions(code_obj)
            optimized_instructions = self._optimize_instructions(instructions)
            _accepted, optimized = rebuild_code_object(code_obj, optimized_instructions)
        except Exception:
            telemetry.record_bytecode_optimization_failed(
                filename=getattr(code_obj, "co_filename", "unknown"),
                name=getattr(code_obj, "co_name", "unknown"),
            )
            return code_obj
        else:
            return optimized

    def remove_breakpoints(self, code_obj: CodeType) -> CodeType:
        """Remove any injected breakpoints from a code object.

        Args:
            code_obj: The code object to clean

        Returns:
            CodeType: Cleaned code object

        """
        try:
            instructions = get_instructions(code_obj)
            cleaned_instructions = []

            i = 0
            while i < len(instructions):
                instr = instructions[i]

                # Skip breakpoint instruction sequences
                if self._is_breakpoint_sequence(instructions, i):
                    # Skip the entire breakpoint sequence
                    i += self._get_breakpoint_sequence_length(instructions, i)
                    continue

                cleaned_instructions.append(instr)
                i += 1

            _accepted, cleaned = rebuild_code_object(code_obj, cleaned_instructions)

        except Exception:
            telemetry.record_bytecode_optimization_failed(
                filename=getattr(code_obj, "co_filename", "unknown"),
                name=getattr(code_obj, "co_name", "unknown"),
            )
            return code_obj
        else:
            return cleaned

    def _get_cache_key(
        self,
        code_obj: CodeType,
        breakpoint_lines: set[int],
    ) -> tuple[str, str, int, tuple[int, ...]]:
        """Generate a cache key for a code object and breakpoint set."""
        return (
            code_obj.co_filename,
            code_obj.co_name,
            code_obj.co_firstlineno,
            tuple(sorted(breakpoint_lines)),
        )

    def _find_injection_points(
        self,
        instructions: list[dis.Instruction],
        breakpoint_lines: set[int],
    ) -> dict[int, int]:
        """Find the best injection points for breakpoints.

        Returns a dict mapping line numbers to instruction indices.
        """
        injection_points = {}

        for i, instr in enumerate(instructions):
            if instr.starts_line is not None and instr.starts_line in breakpoint_lines:
                # Prefer to inject after certain instruction types
                if instr.opname in ("LOAD_CONST", "LOAD_FAST", "LOAD_GLOBAL", "STORE_FAST"):
                    injection_points[instr.starts_line] = i + 1
                else:
                    injection_points[instr.starts_line] = i

        return injection_points

    def _create_breakpoint_instructions(
        self,
        original_instructions: list[dis.Instruction],
        injection_points: dict[int, int],
    ) -> list[dis.Instruction]:
        """Create new instruction list with breakpoints injected."""
        new_instructions = []
        breakpoint_code_cache = {}

        for i, instr in enumerate(original_instructions):
            new_instructions.append(instr)

            # Check if we need to inject a breakpoint after this instruction
            line_to_check = None
            for line, injection_index in injection_points.items():
                if injection_index == i + 1:  # Inject after current instruction
                    line_to_check = line
                    break

            if line_to_check is not None:
                # Get or create breakpoint wrapper code
                if line_to_check not in breakpoint_code_cache:
                    breakpoint_code_cache[line_to_check] = self.create_breakpoint_wrapper_code(
                        line_to_check,
                    )

                # Add breakpoint check instructions
                breakpoint_instrs = self._create_breakpoint_check_instructions(line_to_check)
                new_instructions.extend(breakpoint_instrs)

        return new_instructions

    def _create_breakpoint_check_instructions(self, line: int) -> list[dis.Instruction]:
        """Create instructions for a breakpoint check."""
        # For now, create a simple call to a breakpoint function
        # This will be enhanced in the integration step

        return [
            dis.Instruction(
                opname="LOAD_CONST",
                opcode=LOAD_CONST,
                arg=0,
                argval=line,
                argrepr=str(line),
                offset=0,
                starts_line=None,
                is_jump_target=False,
            ),
            dis.Instruction(
                opname="CALL_FUNCTION",
                opcode=CALL_FUNCTION,
                arg=1,
                argval=1,
                argrepr="",
                offset=2,
                starts_line=None,
                is_jump_target=False,
            ),
            dis.Instruction(
                opname="POP_TOP",
                opcode=POP_TOP,
                arg=None,
                argval=None,
                argrepr="",
                offset=4,
                starts_line=None,
                is_jump_target=False,
            ),
        ]

    def _optimize_instructions(self, instructions: list[dis.Instruction]) -> list[dis.Instruction]:
        """Optimize a list of instructions for better performance."""
        optimized = []
        i = 0

        while i < len(instructions):
            instr = instructions[i]

            # Skip certain debug instructions in optimized mode
            if instr.opname == "POP_TOP" and i > 0:
                prev_instr = instructions[i - 1]
                if prev_instr.opname == "LOAD_CONST" and prev_instr.argval is None:
                    # Skip LOAD_CONST None; POP_TOP sequence
                    i += 1
                    continue

            # Optimize consecutive LOAD_CONST operations
            if instr.opname == "LOAD_CONST" and i + 1 < len(instructions):
                next_instr = instructions[i + 1]
                if next_instr.opname == "POP_TOP" and next_instr.arg is None:
                    # Skip this optimization for now to maintain correctness
                    pass

            optimized.append(instr)
            i += 1

        return optimized

    def _is_breakpoint_sequence(
        self,
        instructions: list[dis.Instruction],
        start_index: int,
    ) -> bool:
        """Check if instructions starting at start_index form a breakpoint sequence."""
        if start_index + 2 >= len(instructions):
            return False

        instr1 = instructions[start_index]
        instr2 = instructions[start_index + 1]
        instr3 = instructions[start_index + 2]

        return (
            instr1.opname == "LOAD_CONST"
            and isinstance(instr1.argval, int)
            and instr2.opname == "CALL_FUNCTION"
            and instr3.opname == "POP_TOP"
        )

    def _get_breakpoint_sequence_length(
        self,
        instructions: list[dis.Instruction],
        start_index: int,
    ) -> int:
        """Get the length of a breakpoint instruction sequence."""
        if self._is_breakpoint_sequence(instructions, start_index):
            return 3
        return 1

    def _rebuild_code_object(
        self,
        original_code: CodeType,
        new_instructions: list[dis.Instruction],
    ) -> tuple[bool, CodeType]:
        """Delegate to the module-level :func:`rebuild_code_object`."""
        return rebuild_code_object(original_code, new_instructions)


# Global bytecode modifier instance
_bytecode_modifier = BytecodeModifier()


def insert_code(
    code_obj: CodeType,
    line: int,
    break_at_lines: tuple[int, ...],
) -> tuple[bool, CodeType]:
    """Insert debugging code into a Python code object.

    This function safely modifies bytecode to inject breakpoint checks
    at specific line numbers without changing the code's behavior.

    Args:
        code_obj: The original code object to modify
        line: The line number to insert at (must be non-negative)
        break_at_lines: Tuple of line numbers that should break

    Returns:
        tuple: (success, modified_code_obj) where success is bool

    """
    # Validate line number
    if line < 0:
        return False, code_obj

    try:
        # Use the advanced bytecode modifier
        breakpoint_lines = set(break_at_lines)
        success, modified_code = _bytecode_modifier.inject_breakpoints(
            code_obj,
            breakpoint_lines,
            debug_mode=True,
        )
    except Exception:
        # If anything goes wrong, return original code object
        telemetry.record_bytecode_injection_failed(
            filename=getattr(code_obj, "co_filename", "unknown"),
            name=getattr(code_obj, "co_name", "unknown"),
            line=line,
        )
        return False, code_obj
    else:
        return success, modified_code


def create_breakpoint_instruction(line: int) -> bytes:
    """Create bytecode for a breakpoint check at a specific line.

    Args:
        line: The line number for the breakpoint

    Returns:
        bytes: Bytecode for the breakpoint instruction

    """
    # This creates a simple breakpoint instruction that will
    # call the frame evaluation hook
    instructions = [
        make_instruction(
            opname="LOAD_CONST",
            opcode=LOAD_CONST,
            arg=0,
            argval=line,
            argrepr=f"{line}",
            offset=0,
            starts_line=line,
            is_jump_target=False,
        ),
        make_instruction(
            opname="CALL_FUNCTION",
            opcode=CALL_FUNCTION,
            arg=1,
            argval=1,
            argrepr="",
            offset=2,
            starts_line=None,
            is_jump_target=False,
        ),
        make_instruction(
            opname="POP_TOP",
            opcode=POP_TOP,
            arg=None,
            argval=None,
            argrepr="",
            offset=4,
            starts_line=None,
            is_jump_target=False,
        ),
    ]

    # Convert instructions to bytecode
    bytecode = bytearray()
    for instr in instructions:
        bytecode.append(instr.opcode)
        if instr.arg is not None:
            bytecode.extend(instr.arg.to_bytes(2, "little"))

    return bytes(bytecode)


def optimize_bytecode(code_obj: CodeType) -> CodeType:
    """Optimize a code object for better frame evaluation performance.

    Args:
        code_obj: The code object to optimize

    Returns:
        CodeType: Optimized code object

    """
    return _bytecode_modifier.optimize_code_object(code_obj)


def validate_bytecode(code_obj: CodeType) -> bool:
    """Validate that a code object has correct bytecode.

    Args:
        code_obj: The code object to validate

    Returns:
        bool: True if bytecode is valid

    """
    try:
        # Try to disassemble the code
        list(dis.get_instructions(code_obj))
    except Exception:
        return False
    else:
        return True


def inject_breakpoint_bytecode(
    code_obj: CodeType,
    breakpoint_lines: set[int],
) -> tuple[bool, CodeType]:
    """Inject breakpoint bytecode into a code object.

    Args:
        code_obj: The code object to modify
        breakpoint_lines: Set of line numbers with breakpoints

    Returns:
        tuple: (success, modified_code_obj)

    """
    return _bytecode_modifier.inject_breakpoints(code_obj, breakpoint_lines)


def remove_breakpoint_bytecode(code_obj: CodeType) -> CodeType:
    """Remove any injected breakpoint bytecode from a code object.

    Args:
        code_obj: The code object to clean

    Returns:
        CodeType: Cleaned code object

    """
    return _bytecode_modifier.remove_breakpoints(code_obj)


def clear_bytecode_cache() -> None:
    """Clear the bytecode modification cache."""
    _bytecode_modifier.modified_code_objects.clear()


def get_bytecode_info(code_obj: CodeType) -> BytecodeInfo | BytecodeErrorInfo:
    """Get information about a code object's bytecode.

    Args:
        code_obj: The code object to analyze

    Returns:
        BytecodeInfo: Information about the bytecode

    """
    try:
        instructions = list(dis.get_instructions(code_obj))

        return {
            "instruction_count": len(instructions),
            "has_breakpoints": any(
                # ruff: noqa: SLF001 - Intentional access to private method for bytecode analysis
                _bytecode_modifier._is_breakpoint_sequence(instructions, i)
                for i in range(len(instructions))
            ),
            "stack_size": code_obj.co_stacksize,
            "flags": code_obj.co_flags,
            "first_lineno": code_obj.co_firstlineno,
            "filename": code_obj.co_filename,
            "name": code_obj.co_name,
            "constants_count": len(code_obj.co_consts),
            "names_count": len(code_obj.co_names),
            "varnames_count": len(code_obj.co_varnames),
        }
    except Exception:
        return {
            "error": "Failed to analyze bytecode",
            "filename": getattr(code_obj, "co_filename", "unknown"),
            "name": getattr(code_obj, "co_name", "unknown"),
        }


def set_optimization_enabled(enabled: bool) -> None:
    """Enable or disable bytecode optimization.

    Args:
        enabled: Whether to enable optimization

    """
    _bytecode_modifier.optimization_enabled = enabled


def get_cache_stats() -> dict[str, Any]:
    """Get statistics about the bytecode modification cache."""
    return {
        "cached_code_objects": len(_bytecode_modifier.modified_code_objects),
        "breakpoint_counter": _bytecode_modifier.breakpoint_counter,
        "optimization_enabled": _bytecode_modifier.optimization_enabled,
    }
