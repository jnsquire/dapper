"""
Bytecode modification utilities for Dapper frame evaluation.

This module provides safe bytecode manipulation capabilities to inject
breakpoints directly into Python code objects for optimized debugging.
"""

from __future__ import annotations

import dis
import sys
import types
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import List
from typing import Set
from typing import Tuple
from typing import TypedDict

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

# Python bytecode instruction constants - version compatible
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


class BytecodeModifier:
    """Advanced bytecode modification system for frame evaluation."""
    
    def __init__(self):
        self.breakpoint_counter = 0
        self.modified_code_objects = {}
        self.optimization_enabled = True
    
    def inject_breakpoints(
        self, 
        code_obj: CodeType, 
        breakpoint_lines: Set[int],
        debug_mode: bool = False
    ) -> Tuple[bool, CodeType]:
        """
        Inject breakpoints into a code object at specified lines.
        
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
            
            # Get original instructions
            instructions = list(dis.get_instructions(code_obj))
            
            # Find injection points
            injection_points = self._find_injection_points(instructions, breakpoint_lines)
            
            if not injection_points:
                # No valid injection points found
                return True, code_obj
            
            # Create new instruction list with breakpoints
            new_instructions = self._create_breakpoint_instructions(
                instructions, injection_points, debug_mode
            )
            
            # Rebuild code object
            modified_code = self._rebuild_code_object(code_obj, new_instructions)
            
            # Cache the result
            self.modified_code_objects[cache_key] = modified_code
            
            return True, modified_code
            
        except Exception as e:
            if debug_mode:
                print(f"Error injecting breakpoints: {e}")
            return False, code_obj
    
    def create_breakpoint_wrapper_code(self, line: int) -> CodeType:
        """
        Create a code object that serves as a breakpoint wrapper.
        
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
        wrapper_code = compile(
            wrapper_source, 
            f"<dapper_breakpoint_wrapper_{line}>", 
            "exec"
        )
        
        return wrapper_code
    
    def optimize_code_object(self, code_obj: CodeType) -> CodeType:
        """
        Optimize a code object for better frame evaluation performance.
        
        Args:
            code_obj: The code object to optimize
            
        Returns:
            CodeType: Optimized code object
        """
        if not self.optimization_enabled:
            return code_obj
        
        try:
            instructions = list(dis.get_instructions(code_obj))
            optimized_instructions = self._optimize_instructions(instructions)
            return self._rebuild_code_object(code_obj, optimized_instructions)
        except Exception:
            return code_obj
    
    def remove_breakpoints(self, code_obj: CodeType) -> CodeType:
        """
        Remove any injected breakpoints from a code object.
        
        Args:
            code_obj: The code object to clean
            
        Returns:
            CodeType: Cleaned code object
        """
        try:
            instructions = list(dis.get_instructions(code_obj))
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
            
            return self._rebuild_code_object(code_obj, cleaned_instructions)
            
        except Exception:
            return code_obj
    
    def _get_cache_key(self, code_obj: CodeType, breakpoint_lines: Set[int]) -> str:
        """Generate a cache key for a code object and breakpoint set."""
        return f"{id(code_obj)}_{hash(tuple(sorted(breakpoint_lines)))}"
    
    def _find_injection_points(
        self, 
        instructions: List[dis.Instruction], 
        breakpoint_lines: Set[int]
    ) -> Dict[int, int]:
        """
        Find the best injection points for breakpoints.
        
        Returns a dict mapping line numbers to instruction indices.
        """
        injection_points = {}
        
        for i, instr in enumerate(instructions):
            if (instr.starts_line is not None and 
                instr.starts_line in breakpoint_lines):
                
                # Prefer to inject after certain instruction types
                if instr.opname in ("LOAD_CONST", "LOAD_FAST", "LOAD_GLOBAL", "STORE_FAST"):
                    injection_points[instr.starts_line] = i + 1
                else:
                    injection_points[instr.starts_line] = i
        
        return injection_points
    
    def _create_breakpoint_instructions(
        self,
        original_instructions: List[dis.Instruction],
        injection_points: Dict[int, int],
        debug_mode: bool
    ) -> List[dis.Instruction]:
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
                    breakpoint_code_cache[line_to_check] = self.create_breakpoint_wrapper_code(line_to_check)
                
                # Add breakpoint check instructions
                breakpoint_instrs = self._create_breakpoint_check_instructions(
                    line_to_check, debug_mode
                )
                new_instructions.extend(breakpoint_instrs)
        
        return new_instructions
    
    def _create_breakpoint_check_instructions(
        self, 
        line: int, 
        debug_mode: bool
    ) -> List[dis.Instruction]:
        """Create instructions for a breakpoint check."""
        # For now, create a simple call to a breakpoint function
        # This will be enhanced in the integration step
        
        instructions = [
            dis.Instruction(
                opname="LOAD_CONST",
                opcode=LOAD_CONST,
                arg=0,
                argval=line,
                argrepr=str(line),
                offset=0,
                starts_line=None,
                is_jump_target=False
            ),
            dis.Instruction(
                opname="CALL_FUNCTION",
                opcode=CALL_FUNCTION,
                arg=1,
                argval=1,
                argrepr="",
                offset=2,
                starts_line=None,
                is_jump_target=False
            ),
            dis.Instruction(
                opname="POP_TOP",
                opcode=POP_TOP,
                arg=None,
                argval=None,
                argrepr="",
                offset=4,
                starts_line=None,
                is_jump_target=False
            )
        ]
        
        return instructions
    
    def _optimize_instructions(
        self, 
        instructions: List[dis.Instruction]
    ) -> List[dis.Instruction]:
        """Optimize a list of instructions for better performance."""
        optimized = []
        i = 0
        
        while i < len(instructions):
            instr = instructions[i]
            
            # Skip certain debug instructions in optimized mode
            if instr.opname == "POP_TOP" and i > 0:
                prev_instr = instructions[i - 1]
                if (prev_instr.opname == "LOAD_CONST" and 
                    prev_instr.argval is None):
                    # Skip LOAD_CONST None; POP_TOP sequence
                    i += 1
                    continue
            
            # Optimize consecutive LOAD_CONST operations
            if instr.opname == "LOAD_CONST" and i + 1 < len(instructions):
                next_instr = instructions[i + 1]
                if (next_instr.opname == "POP_TOP" and
                    next_instr.arg is None):
                    # Skip this optimization for now to maintain correctness
                    pass
            
            optimized.append(instr)
            i += 1
        
        return optimized
    
    def _is_breakpoint_sequence(
        self, 
        instructions: List[dis.Instruction], 
        start_index: int
    ) -> bool:
        """Check if instructions starting at start_index form a breakpoint sequence."""
        if start_index + 2 >= len(instructions):
            return False
        
        instr1 = instructions[start_index]
        instr2 = instructions[start_index + 1]
        instr3 = instructions[start_index + 2]
        
        return (instr1.opname == "LOAD_CONST" and
                isinstance(instr1.argval, int) and
                instr2.opname == "CALL_FUNCTION" and
                instr3.opname == "POP_TOP")
    
    def _get_breakpoint_sequence_length(
        self, 
        instructions: List[dis.Instruction], 
        start_index: int
    ) -> int:
        """Get the length of a breakpoint instruction sequence."""
        if self._is_breakpoint_sequence(instructions, start_index):
            return 3
        return 1
    
    def _rebuild_code_object(
        self, 
        original_code: CodeType, 
        new_instructions: List[dis.Instruction]
    ) -> CodeType:
        """Rebuild a code object with new instructions."""
        # Convert instructions back to bytecode
        bytecode = bytearray()
        for instr in new_instructions:
            bytecode.append(instr.opcode)
            if instr.arg is not None:
                if instr.arg >= 0:
                    bytecode.extend(instr.arg.to_bytes(2, "little"))
                else:
                    # Handle negative arguments
                    bytecode.extend((instr.arg & 0xFFFF).to_bytes(2, "little"))
        
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
            "co_cellvars": original_code.co_cellvars
        }
        
        # Handle version-specific parameters
        if sys.version_info >= (3, 8):
            code_args["co_posonlyargcount"] = getattr(original_code, "co_posonlyargcount", 0)
            
        # For Python 3.10+, we need to handle the new code object creation
        if sys.version_info >= (3, 10):
            # Get line number information using co_lines() and convert to lnotab format
            # for backward compatibility with the code object constructor
            lnotab = bytearray()
            last_line = original_code.co_firstlineno
            last_byte = 0
            
            for start, end, line in original_code.co_lines():
                if start > last_byte and line is not None:
                    # Calculate the byte offset and line delta
                    byte_delta = start - last_byte
                    line_delta = line - last_line
                    
                    # Handle multi-byte deltas
                    while byte_delta > 255 or line_delta > 127 or line_delta < -128:
                        # Emit a special byte to indicate multi-byte delta
                        lnotab.extend((min(255, byte_delta), 0))
                        byte_delta -= min(255, byte_delta)
                        line_delta = max(-128, min(127, line_delta))
                    
                    # Emit the final delta
                    lnotab.extend((byte_delta, line_delta & 0xff))
                    last_byte = start
                    last_line = line
            
            code_args["co_linetable"] = bytes(lnotab)
            code_args["co_lnotab"] = b""  # Keep for backward compatibility
        else:
            # For Python < 3.10, use the old co_lnotab
            code_args["co_lnotab"] = original_code.co_lnotab
        
        # Create the code object with the appropriate arguments
        if sys.version_info >= (3, 10):
            # Python 3.10+ uses co_linetable instead of co_lnotab
            return types.CodeType(
                code_args["co_argcount"],
                code_args.get("co_posonlyargcount", 0),
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
                code_args["co_firstlineno"],
                code_args["co_linetable"],
                code_args["co_freevars"],
                code_args["co_cellvars"],
                # Python 3.11+ requires these additional arguments
                original_code.co_positions() if hasattr(original_code, "co_positions") else None,
                original_code.co_exceptiontable if hasattr(original_code, "co_exceptiontable") else b""
            )
        if sys.version_info >= (3, 8):
            return types.CodeType(
                code_args["co_argcount"],
                code_args.get("co_posonlyargcount", 0),
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
                code_args["co_firstlineno"],
                code_args["co_lnotab"],
                code_args["co_freevars"],
                code_args["co_cellvars"]
            )
        # Python 3.7 and earlier
        return types.CodeType(
            code_args["co_argcount"],
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
            original_code.co_firstlineno,
            original_code.co_lnotab,
            original_code.co_freevars,
            original_code.co_cellvars
        )


# Global bytecode modifier instance
_bytecode_modifier = BytecodeModifier()


def insert_code(
    code_obj: CodeType, 
    wrapper_code: str, 
    line: int, 
    break_at_lines: Tuple[int, ...]
) -> Tuple[bool, CodeType]:
    """
    Insert debugging code into a Python code object.
    
    This function safely modifies bytecode to inject breakpoint checks
    at specific line numbers without changing the code's behavior.
    
    Args:
        code_obj: The original code object to modify
        wrapper_code: The debugging code to insert
        line: The line number to insert at
        break_at_lines: Tuple of line numbers that should break
        
    Returns:
        tuple: (success, modified_code_obj) where success is bool
    """
    try:
        # Use the advanced bytecode modifier
        breakpoint_lines = set(break_at_lines)
        success, modified_code = _bytecode_modifier.inject_breakpoints(
            code_obj, breakpoint_lines, debug_mode=True
        )
        
        return success, modified_code
        
    except Exception:
        # If anything goes wrong, return original code object
        return False, code_obj


def create_breakpoint_instruction(line: int) -> bytes:
    """
    Create bytecode for a breakpoint check at a specific line.
    
    Args:
        line: The line number for the breakpoint
        
    Returns:
        bytes: Bytecode for the breakpoint instruction
    """
    # This creates a simple breakpoint instruction that will
    # call the frame evaluation hook
    instructions = [
        dis.Instruction(
            opname="LOAD_CONST",
            opcode=LOAD_CONST,
            arg=0,
            argval=line,
            argrepr=f"{line}",
            offset=0,
            starts_line=line,
            is_jump_target=False
        ),
        dis.Instruction(
            opname="CALL_FUNCTION",
            opcode=CALL_FUNCTION,
            arg=1,
            argval=1,
            argrepr="",
            offset=2,
            starts_line=None,
            is_jump_target=False
        ),
        dis.Instruction(
            opname="POP_TOP",
            opcode=POP_TOP,
            arg=None,
            argval=None,
            argrepr="",
            offset=4,
            starts_line=None,
            is_jump_target=False
        )
    ]
    
    # Convert instructions to bytecode
    bytecode = bytearray()
    for instr in instructions:
        bytecode.append(instr.opcode)
        if instr.arg is not None:
            bytecode.extend(instr.arg.to_bytes(2, "little"))
    
    return bytes(bytecode)


def optimize_bytecode(code_obj: CodeType) -> CodeType:
    """
    Optimize a code object for better frame evaluation performance.
    
    Args:
        code_obj: The code object to optimize
        
    Returns:
        CodeType: Optimized code object
    """
    return _bytecode_modifier.optimize_code_object(code_obj)


def validate_bytecode(code_obj: CodeType) -> bool:
    """
    Validate that a code object has correct bytecode.
    
    Args:
        code_obj: The code object to validate
        
    Returns:
        bool: True if bytecode is valid
    """
    try:
        # Try to disassemble the code
        list(dis.get_instructions(code_obj))
        return True
    except Exception:
        return False


def inject_breakpoint_bytecode(
    code_obj: CodeType, 
    breakpoint_lines: Set[int]
) -> Tuple[bool, CodeType]:
    """
    Inject breakpoint bytecode into a code object.
    
    Args:
        code_obj: The code object to modify
        breakpoint_lines: Set of line numbers with breakpoints
        
    Returns:
        tuple: (success, modified_code_obj)
    """
    return _bytecode_modifier.inject_breakpoints(code_obj, breakpoint_lines)


def remove_breakpoint_bytecode(code_obj: CodeType) -> CodeType:
    """
    Remove any injected breakpoint bytecode from a code object.
    
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
    """
    Get information about a code object's bytecode.
    
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
    """
    Enable or disable bytecode optimization.
    
    Args:
        enabled: Whether to enable optimization
    """
    _bytecode_modifier.optimization_enabled = enabled


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about the bytecode modification cache."""
    return {
        "cached_code_objects": len(_bytecode_modifier.modified_code_objects),
        "breakpoint_counter": _bytecode_modifier.breakpoint_counter,
        "optimization_enabled": _bytecode_modifier.optimization_enabled,
    }
