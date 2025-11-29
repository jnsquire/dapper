"""
Canonical DAP command handler implementations and registry for the debuggee process.

This module provides:
1. The `COMMAND_HANDLERS` registry populated via the `@command_handler` decorator
2. The canonical handler implementations for all DAP commands
3. The `handle_debug_command()` entry point for command dispatch

Both IPC pathways dispatch through the `COMMAND_HANDLERS` registry:
- Pipe-based IPC: `debug_launcher.py` calls `handle_debug_command()`
- Socket-based IPC: `ipc_receiver.py` wraps `COMMAND_HANDLERS` in a provider

Dependencies:
- `dapper.launcher.comm.send_debug_message` for IPC message output
- `dapper.shared.debug_shared.state` for debugger session state
"""

from __future__ import annotations

import ast
import linecache
import mimetypes
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.launcher.comm import send_debug_message
from dapper.shared import debug_shared as _d_shared
from dapper.shared.debug_shared import state

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import Module
    from dapper.protocol.requests import SetExceptionBreakpointsResponse
    from dapper.protocol.requests import SetFunctionBreakpointsArguments
    from dapper.protocol.structures import Source

VAR_REF_TUPLE_SIZE = 2
SIMPLE_FN_ARGCOUNT = 2
_CONVERSION_FAILED = object()
_convert_value_with_context_override: Any | None = None

# =============================================================================
# Command Registry
# =============================================================================

# Command mapping table - populated by the @command_handler decorator
COMMAND_HANDLERS: dict[str, Any] = {}


def command_handler(command_name: str):
    """Decorator to register DAP command handlers in the COMMAND_HANDLERS registry."""

    def decorator(func):
        COMMAND_HANDLERS[command_name] = func
        return func

    return decorator


def handle_debug_command(command: dict[str, Any]) -> None:
    """Handle debug commands using the COMMAND_HANDLERS registry.
    
    This is the main entry point for command dispatch. Both IPC pathways
    (pipe-based and socket-based) ultimately dispatch through this registry.
    """
    cmd = command.get("command")
    arguments = command.get("arguments", {})

    # Look up the command handler in the mapping table
    handler_func = COMMAND_HANDLERS.get(cmd)
    if handler_func is not None:
        handler_func(arguments)
    else:
        send_debug_message(
            "response",
            request_seq=command.get("seq"),
            success=False,
            message=f"Unknown command: {cmd}",
        )


# =============================================================================
# Helper Functions
# =============================================================================

# Back-compat: expose make_variable_object at module level for tests
make_variable_object = _d_shared.make_variable_object


def _make_variable(dbg: DebuggerLike | None, name: str, value: Any, frame: Any | None) -> Variable:
    """Create a Variable object using the debugger-provided factory if available."""
    fn = getattr(dbg, "make_variable_object", None) if dbg is not None else None
    var_obj = None
    if callable(fn):
        try:
            if getattr(fn, "__code__", None) is not None and fn.__code__.co_argcount > SIMPLE_FN_ARGCOUNT:
                var_obj = fn(name, value, frame)
            else:
                var_obj = fn(name, value)
        except Exception:
            var_obj = None

    if not isinstance(var_obj, dict):
        var_obj = _d_shared.make_variable_object(name, value, dbg, frame)

    return cast("Variable", var_obj)


def _get_threading_module() -> Any:
    """Return the threading module used for thread identification."""
    return threading


def _get_thread_ident() -> int:
    """Return the current thread id."""
    thread_mod = _get_threading_module()
    return thread_mod.get_ident()


def _set_dbg_stepping_flag(dbg: DebuggerLike) -> None:
    """Ensure the debugger reports a stepping state."""
    try:
        dbg.stepping = True
    except Exception:
        pass
    try:
        object.__setattr__(dbg, "stepping", True)
    except Exception:
        pass


def _call_convert_callable(convert: Any, value_str: str, frame: Any | None, parent_obj: Any | None) -> Any:
    try:
        return convert(value_str, frame, parent_obj)
    except TypeError:
        return convert(value_str)


def _try_custom_convert(value_str: str, frame: Any | None = None, parent_obj: Any | None = None) -> Any:
    converter = globals().get("_convert_value_with_context_override")
    if converter is not None:
        try:
            return _call_convert_callable(converter, value_str, frame, parent_obj)
        except Exception:
            pass

    try:
        return _convert_value_with_context(value_str, frame, parent_obj)
    except Exception:
        pass

    return _CONVERSION_FAILED


def _convert_value_with_context(value_str: str, frame: Any | None = None, parent_obj: Any | None = None) -> Any:
    """Convert a string value to a Python object using available context."""
    s = value_str.strip()
    if s.lower() == "none":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"

    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        pass

    if frame is not None:
        try:
            return eval(s, frame.f_globals, frame.f_locals)
        except Exception:
            pass

    if parent_obj is not None:
        try:
            target_type = None
            if isinstance(parent_obj, list) and parent_obj:
                target_type = type(parent_obj[0])
            elif isinstance(parent_obj, dict) and parent_obj:
                sample = next(iter(parent_obj.values()))
                target_type = type(sample)

            if target_type in (int, float, bool, str):
                return target_type(s)
        except Exception:
            pass

    return value_str


def _convert_string_to_value(value_str: str) -> Any:
    """Legacy alias kept for backward compatibility."""
    return _convert_value_with_context(value_str)


def _resolve_variables_for_reference(dbg: DebuggerLike | None, frame_info: Any) -> list[Variable]:
    """Return variables for a var_refs entry."""
    vars_out: list[Variable] = []

    if isinstance(frame_info, list):
        vars_out.extend([cast("Variable", v) for v in frame_info if isinstance(v, dict)])
        return vars_out

    if not (isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE):
        return vars_out

    kind, payload = frame_info

    if kind == "object":
        parent_obj = payload

        def _extract_variables(parent):
            if isinstance(parent, dict):
                for name, val in parent.items():
                    vars_out.append(_make_variable(dbg, name, val, None))
            elif isinstance(parent, list):
                for idx, val in enumerate(parent):
                    vars_out.append(_make_variable(dbg, str(idx), val, None))
            else:
                for name in dir(parent):
                    if name.startswith("_"):
                        continue
                    try:
                        val = getattr(parent, name)
                    except Exception:
                        continue
                    vars_out.append(_make_variable(dbg, name, val, None))

        _extract_variables(parent_obj)
        return vars_out

    if isinstance(kind, int) and payload in ("locals", "globals"):
        frame_id = kind
        scope = payload
        frame = getattr(dbg, "frame_id_to_frame", {}).get(frame_id)
        if not frame:
            return []

        mapping = frame.f_locals if scope == "locals" else frame.f_globals
        vars_out.extend(_extract_variables_from_mapping(dbg, mapping, frame))
        return vars_out

    return vars_out


def _extract_variables_from_mapping(dbg: DebuggerLike | None, mapping: dict[str, Any], frame: Any | None) -> list[Variable]:
    """Convert a mapping of names -> values into a list of Variable objects."""
    out: list[Variable] = []
    for name, val in mapping.items():
        out.append(_make_variable(dbg, name, val, frame))
    return out


def _set_scope_variable(frame: Any, scope: str, name: str, value_str: str) -> dict[str, Any]:
    """Set a variable in a frame scope (locals or globals)."""
    try:
        new_value = _try_custom_convert(value_str, frame, None)
        if new_value is _CONVERSION_FAILED:
            new_value = eval(value_str, frame.f_globals, frame.f_locals)
    except Exception:
        new_value = _convert_value_with_context(value_str, frame)

    if scope == "locals":
        frame.f_locals[name] = new_value
    elif scope == "globals":
        frame.f_globals[name] = new_value
    else:
        return {"success": False, "message": f"Unknown scope: {scope}"}

    dbg = state.debugger
    var_obj = _make_variable(dbg, name, new_value, frame)
    return {
        "success": True,
        "body": {
            "value": cast("dict", var_obj)["value"],
            "type": cast("dict", var_obj)["type"],
            "variablesReference": cast("dict", var_obj)["variablesReference"],
        },
    }


def _set_object_member(parent_obj: Any, name: str, value_str: str) -> dict[str, Any]:
    """Set an attribute or item of an object."""
    try:
        new_value = _try_custom_convert(value_str, None, parent_obj)
        if new_value is _CONVERSION_FAILED:
            new_value = _convert_value_with_context(value_str, None, parent_obj)
    except Exception:
        return {"success": False, "message": "Conversion failed"}

    err = _assign_to_parent_member(parent_obj, name, new_value)

    try:
        if err is not None:
            return {"success": False, "message": err}

        dbg = state.debugger
        var_obj = _make_variable(dbg, name, new_value, None)
        return {
            "success": True,
            "body": {
                "value": cast("dict", var_obj)["value"],
                "type": cast("dict", var_obj)["type"],
                "variablesReference": cast("dict", var_obj)["variablesReference"],
            },
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to set object member '{name}': {e!s}"}


def _assign_to_parent_member(parent_obj: Any, name: str, new_value: Any) -> str | None:
    """Assign value into parent container/object. Returns error message on failure."""
    err: str | None = None

    if isinstance(parent_obj, dict):
        parent_obj[name] = new_value
    elif isinstance(parent_obj, list):
        try:
            index = int(name)
        except Exception:
            err = f"Invalid list index: {name}"
        else:
            if not (0 <= index < len(parent_obj)):
                err = f"List index {index} out of range"
            else:
                parent_obj[index] = new_value
    elif isinstance(parent_obj, tuple):
        err = "Cannot modify tuple - tuples are immutable"
    else:
        try:
            setattr(parent_obj, name, new_value)
        except Exception as e:
            err = f"Cannot set attribute '{name}' on {type(parent_obj).__name__}: {e!s}"

    return err


def extract_variables(dbg: Any, variables: list[dict[str, Any]], parent: Any, _name: str | None = None) -> None:
    """Recursively extract variables from a dict/list/object into variables list."""
    def _create_variable_object(key: str, val: Any) -> dict[str, Any]:
        return cast("dict", _make_variable(dbg, key, val, None))

    if isinstance(parent, dict):
        for key, val in parent.items():
            variables.append(_create_variable_object(key, val))
        return

    if isinstance(parent, (list, tuple)):
        for i, val in enumerate(parent):
            variables.append(_create_variable_object(str(i), val))
        return

    for attr in dir(parent):
        if str(attr).startswith("_"):
            continue
        try:
            val = getattr(parent, attr)
            variables.append(_create_variable_object(attr, val))
        except Exception:
            continue


# =============================================================================
# Source Collection Helpers (for loadedSources handler)
# =============================================================================

def _collect_module_sources(seen_paths: set[str]) -> list[Source]:
    """Collect sources from sys.modules."""
    from dapper.protocol.structures import Source  # noqa: PLC0415
    
    sources: list[Source] = []

    for module_name, module in sys.modules.items():
        if module is None:
            continue

        try:
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                continue

            module_path = Path(module_file).resolve()
            module_file = str(module_path)

            if module_file in seen_paths:
                continue
            if not module_file.endswith((".py", ".pyw")):
                continue

            seen_paths.add(module_file)

            origin = getattr(module, "__package__", module_name)
            source_obj = Source(name=module_path.name, path=module_file, origin=f"module:{origin}")
            sources.append(source_obj)

        except (AttributeError, TypeError, OSError):
            continue

    return sources


def _collect_linecache_sources(seen_paths: set[str]) -> list[Source]:
    """Collect sources from linecache."""
    from dapper.protocol.structures import Source  # noqa: PLC0415
    
    sources: list[Source] = []

    for filename in linecache.cache:
        if filename not in seen_paths and filename.endswith((".py", ".pyw")):
            try:
                file_path = Path(filename).resolve()
                abs_path = str(file_path)
                if abs_path not in seen_paths and file_path.exists():
                    seen_paths.add(abs_path)
                    source = Source(name=file_path.name, path=abs_path, origin="linecache")
                    sources.append(source)
            except (OSError, TypeError):
                continue

    return sources


def _collect_main_program_source(seen_paths: set[str]) -> list[Source]:
    """Collect the main program source if available."""
    from dapper.protocol.structures import Source  # noqa: PLC0415
    
    sources: list[Source] = []

    if state.debugger:
        program_path = getattr(state.debugger, "program_path", None)
        if program_path and program_path not in seen_paths:
            try:
                program_file_path = Path(program_path).resolve()
                abs_path = str(program_file_path)
                if program_file_path.exists():
                    sources.append(
                        Source(name=program_file_path.name, path=abs_path, origin="main")
                    )
            except (OSError, TypeError):
                pass

    return sources


# =============================================================================
# Implementation Functions (take dbg, arguments)
# These are the canonical implementations that registered handlers call.
# =============================================================================

def _handle_set_breakpoints_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setBreakpoints command implementation."""
    arguments = arguments or {}
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")

    if path and dbg:
        try:
            dbg.clear_breaks_for_file(path)  # type: ignore[attr-defined]
        except Exception:
            try:
                dbg.clear_break(path)  # type: ignore[misc]
            except Exception:
                try:
                    dbg.clear_break_meta_for_file(path)
                except Exception:
                    pass

        verified_bps: list[dict[str, Any]] = []
        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            verified = True
            if line:
                try:
                    res = dbg.set_break(path, line, cond=condition)
                except Exception:
                    verified = False
                else:
                    verified = res is not False

                try:
                    dbg.record_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                    )
                except Exception:
                    pass

                verified_bps.append({"verified": verified, "line": line})

        try:
            send_debug_message("breakpoints", source=source, breakpoints=verified_bps)
        except Exception:
            pass

        return {"success": True, "body": {"breakpoints": verified_bps}}
    return None


def _handle_set_function_breakpoints_impl(dbg: DebuggerLike, arguments: SetFunctionBreakpointsArguments):
    """Handle setFunctionBreakpoints command implementation."""
    arguments = arguments or {}
    bps = arguments.get("breakpoints", [])

    if dbg:
        dbg.clear_all_function_breakpoints()

        for bp in bps:
            name = bp.get("name")
            if not name:
                continue

            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            dbg.function_breakpoints.append(name)
            try:
                fbm = dbg.function_breakpoint_meta
            except Exception:
                fbm = None
            if isinstance(fbm, dict):
                mb = fbm.get(name, {})
                mb.setdefault("hit", 0)
                mb["condition"] = condition
                mb["hitCondition"] = hit_condition
                mb["logMessage"] = log_message
                fbm[name] = mb

        results: list[dict[str, Any]] = []
        fb_list = getattr(dbg, "function_breakpoints", [])
        for bp in bps:
            name = bp.get("name")
            verified = False
            if name and isinstance(fb_list, list):
                try:
                    verified = name in fb_list
                except Exception:
                    verified = False
            results.append({"verified": verified})

        return {"success": True, "body": {"breakpoints": results}}
    return None


def _handle_set_exception_breakpoints_impl(
    dbg: DebuggerLike, arguments: dict[str, Any]
) -> SetExceptionBreakpointsResponse | None:
    """Handle setExceptionBreakpoints command implementation."""
    arguments = arguments or {}
    raw_filters = arguments.get("filters", [])

    if isinstance(raw_filters, (list, tuple)):
        filters: list[str] = [str(f) for f in raw_filters]
    else:
        filters = []

    if not dbg:
        return None

    verified_all: bool = True
    try:
        dbg.exception_breakpoints_raised = "raised" in filters
        dbg.exception_breakpoints_uncaught = "uncaught" in filters
    except Exception:
        verified_all = False

    body = {"breakpoints": [{"verified": verified_all} for _ in filters]}
    response: dict[str, Any] = {"success": True, "body": body}
    return cast("SetExceptionBreakpointsResponse", response)


def _handle_continue_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle continue command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id in dbg.stopped_thread_ids:
        dbg.stopped_thread_ids.remove(thread_id)
        if not dbg.stopped_thread_ids:
            dbg.set_continue()


def _handle_next_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle next command (step over) implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == _get_thread_ident():
        _set_dbg_stepping_flag(dbg)
        if dbg.current_frame is not None:
            dbg.set_next(dbg.current_frame)


def _handle_step_in_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepIn command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == _get_thread_ident():
        _set_dbg_stepping_flag(dbg)
        dbg.set_step()


def _handle_step_out_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepOut command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == _get_thread_ident():
        _set_dbg_stepping_flag(dbg)
        if dbg.current_frame is not None:
            dbg.set_return(dbg.current_frame)


def _handle_pause_impl(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle pause command implementation."""
    arguments = arguments or {}
    arguments.get("threadId")


def _handle_stack_trace_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stackTrace command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels")

    stack_frames = []

    frames = None
    if dbg and hasattr(dbg, "frames_by_thread") and isinstance(thread_id, int) and thread_id in getattr(dbg, "frames_by_thread", {}):
        frames = dbg.frames_by_thread[thread_id]
    else:
        if dbg:
            stack = getattr(dbg, "stack", None)
            if stack is not None and thread_id == _get_thread_ident():
                frames = stack[start_frame:]
        if levels is not None and frames is not None:
            frames = frames[:levels]

        if frames is not None:
            for i, entry in enumerate(frames, start=start_frame):
                if isinstance(entry, dict):
                    frame = entry
                    name = frame.get("name")
                    source_path = frame.get("file", frame.get("path")) or ""
                    lineno = frame.get("line", 0)
                else:
                    frame, lineno = entry
                    name = frame.f_code.co_name
                    source_path = frame.f_code.co_filename

                stack_frames.append({
                    "id": i,
                    "name": name,
                    "source": {"name": Path(source_path).name, "path": source_path},
                    "line": lineno,
                    "column": 0,
                })

    try:
        send_debug_message(
            "stackTrace",
            threadId=thread_id,
            stackFrames=stack_frames,
            totalFrames=len(stack_frames),
        )
    except Exception:
        pass

    return {"success": True, "body": {"stackFrames": stack_frames}}


def _handle_threads_impl(dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle threads command implementation."""
    threads = []
    if dbg and getattr(dbg, "threads", None):
        for tid, t in dbg.threads.items():
            name = t if isinstance(t, str) else getattr(t, "name", f"Thread-{tid}")
            threads.append({"id": tid, "name": name})
    
    try:
        send_debug_message("threads", threads=threads)
    except Exception:
        pass

    return {"success": True, "body": {"threads": threads}}


def _handle_scopes_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle scopes command implementation."""
    arguments = arguments or {}
    frame_id = arguments.get("frameId")
    
    scopes = []
    if frame_id is not None:
        frame = None
        if dbg and getattr(dbg, "frame_id_to_frame", None):
            frame = dbg.frame_id_to_frame.get(frame_id)
        elif dbg and getattr(dbg, "stack", None):
            try:
                stack = getattr(dbg, "stack", None)
                if stack is not None and frame_id is not None and frame_id < len(stack):
                    frame, _ = stack[frame_id]
                else:
                    frame = None
            except Exception:
                frame = None
        if frame is not None:
            scopes = [
                {
                    "name": "Locals",
                    "variablesReference": frame_id * VAR_REF_TUPLE_SIZE,
                    "expensive": False,
                },
                {
                    "name": "Globals", 
                    "variablesReference": frame_id * VAR_REF_TUPLE_SIZE + 1,
                    "expensive": True,
                },
            ]
    
    try:
        send_debug_message("scopes", scopes=scopes)
    except Exception:
        pass

    return {"success": True, "body": {"scopes": scopes}}


def _handle_variables_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle variables command implementation."""
    arguments = arguments or {}
    variables_reference = arguments.get("variablesReference")

    variables: list[Variable] = []
    if not (dbg and isinstance(variables_reference, int) and variables_reference in getattr(dbg, "var_refs", {})):
        try:
            send_debug_message("variables", variablesReference=variables_reference, variables=variables)
        except Exception:
            pass
        return None

    frame_info = dbg.var_refs[variables_reference]
    variables = _resolve_variables_for_reference(dbg, frame_info)

    try:
        send_debug_message("variables", variablesReference=variables_reference, variables=variables)
    except Exception:
        pass

    return {"success": True, "body": {"variables": variables}}


def _handle_set_variable_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setVariable command implementation."""
    arguments = arguments or {}
    variables_reference = arguments.get("variablesReference")
    name = arguments.get("name")
    value = arguments.get("value")
    
    if not (dbg and isinstance(variables_reference, int) and name and value is not None):
        return {"success": False, "message": "Invalid arguments"}

    if variables_reference not in getattr(dbg, "var_refs", {}):
        return {"success": False, "message": "Invalid variable reference"}

    frame_info = dbg.var_refs[variables_reference]

    try:
        if isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE:
            first, second = frame_info

            if first == "object":
                parent_obj = second
                return _set_object_member(parent_obj, name, value)

            if isinstance(first, int) and second in ("locals", "globals"):
                assert isinstance(first, int)
                frame_id: int = first
                scope: str = second
                frame = getattr(dbg, "frame_id_to_frame", {}).get(frame_id)
                if frame:
                    return _set_scope_variable(frame, scope, name, value)
    except Exception:
        return {"success": False, "message": "Failed to set variable"}

    return {"success": False, "message": f"Invalid variable reference: {variables_reference}"}


def _handle_evaluate_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle evaluate command implementation."""
    arguments = arguments or {}
    expression = arguments.get("expression", "")
    frame_id = arguments.get("frameId")

    result = "<error>"

    if dbg and expression:
        if not isinstance(expression, str):
            raise TypeError("expression must be a string")
        try:
            stack = getattr(dbg, "stack", None)
            if stack and frame_id is not None and frame_id < len(stack):
                frame, _ = stack[frame_id]
                try:
                    value = eval(expression, frame.f_globals, frame.f_locals)
                    result = repr(value)
                except Exception as e:
                    result = f"<error: {e}>"
            elif hasattr(dbg, "current_frame") and dbg.current_frame:
                try:
                    value = eval(expression, dbg.current_frame.f_globals, dbg.current_frame.f_locals)
                    result = repr(value)
                except Exception as e:
                    result = f"<error: {e}>"
        except Exception:
            pass
    
    try:
        send_debug_message(
            "evaluate",
            expression=expression,
            result=result,
            variablesReference=0,
        )
    except Exception:
        pass

    return {
        "success": True,
        "body": {
            "result": result,
            "variablesReference": 0,
        }
    }


def _handle_set_data_breakpoints_impl(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setDataBreakpoints command implementation."""
    arguments = arguments or {}
    breakpoints = arguments.get("breakpoints", [])
    
    clear_all = getattr(dbg, "clear_all_data_breakpoints", None)
    if callable(clear_all):
        try:
            clear_all()
        except Exception:
            pass
    
    results = []
    for bp in breakpoints:
        data_id = bp.get("dataId")
        access_type = bp.get("accessType", "readWrite")
        verified = False
        
        set_db = getattr(dbg, "set_data_breakpoint", None)
        if data_id and callable(set_db):
            try:
                set_db(data_id, access_type)
                verified = True
            except Exception:
                pass
        
        results.append({"verified": verified})
    
    return {"success": True, "body": {"breakpoints": results}}


def _handle_data_breakpoint_info_impl(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle dataBreakpointInfo command implementation."""
    arguments = arguments or {}
    name = arguments.get("name", "")
    variables_reference = arguments.get("variablesReference")
    
    data_id = f"{variables_reference}:{name}" if variables_reference else name
    
    return {
        "success": True,
        "body": {
            "dataId": data_id,
            "description": f"Data breakpoint for {name}",
            "accessTypes": ["read", "write", "readWrite"],
            "canPersist": False,
        }
    }


def _handle_configuration_done_impl(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle configurationDone command implementation."""
    return {"success": True}


def _handle_terminate_impl(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle terminate command implementation."""
    try:
        send_debug_message("exited", exitCode=0)
    except Exception:
        pass
    state.is_terminated = True
    state.exit_func(0)


def _handle_initialize_impl(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle initialize command implementation."""
    capabilities = {
        "supportsConfigurationDoneRequest": True,
        "supportsFunctionBreakpoints": True,
        "supportsExceptionBreakpoints": True,
        "supportsDataBreakpoints": True,
        "supportsSetVariable": True,
        "supportsEvaluateForHovers": True,
        "supportsLogPoints": True,
        "supportsRestartRequest": True,
    }
    
    return {"success": True, "body": capabilities}


def _handle_restart_impl(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle restart command implementation."""
    try:
        send_debug_message("exited", exitCode=0)
    except Exception:
        pass

    python = sys.executable
    argv = sys.argv[1:]
    state.exec_func(python, [python, *argv])

    return {"success": True}


# =============================================================================
# Public API Functions (for backward compatibility with (dbg, arguments) signature)
# These are called by tests that use the old signature.
# =============================================================================

def handle_set_breakpoints(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setBreakpoints command."""
    return _handle_set_breakpoints_impl(dbg, arguments)


def handle_set_function_breakpoints(dbg: DebuggerLike, arguments: SetFunctionBreakpointsArguments):
    """Handle setFunctionBreakpoints command."""
    return _handle_set_function_breakpoints_impl(dbg, arguments)


def handle_set_exception_breakpoints(
    dbg: DebuggerLike, arguments: dict[str, Any]
) -> SetExceptionBreakpointsResponse | None:
    """Handle setExceptionBreakpoints command."""
    return _handle_set_exception_breakpoints_impl(dbg, arguments)


def handle_continue(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle continue command."""
    return _handle_continue_impl(dbg, arguments)


def handle_next(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle next command (step over)."""
    return _handle_next_impl(dbg, arguments)


def handle_step_in(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepIn command."""
    return _handle_step_in_impl(dbg, arguments)


def handle_step_out(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepOut command."""
    return _handle_step_out_impl(dbg, arguments)


def handle_pause(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle pause command."""
    return _handle_pause_impl(dbg, arguments)


def handle_stack_trace(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stackTrace command."""
    return _handle_stack_trace_impl(dbg, arguments)


def handle_threads(dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle threads command."""
    return _handle_threads_impl(dbg, _arguments)


def handle_scopes(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle scopes command."""
    return _handle_scopes_impl(dbg, arguments)


def handle_source(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle source command (legacy signature)."""
    arguments = arguments or {}
    source_reference = arguments.get("sourceReference")
    
    if source_reference:
        content = ""
    else:
        path = arguments.get("path")
        content = ""
        if path:
            try:
                with Path(path).open(encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                content = ""
    
    try:
        send_debug_message("source", content=content)
    except Exception:
        pass

    return {"success": True, "body": {"content": content}}


def handle_variables(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle variables command."""
    return _handle_variables_impl(dbg, arguments)


def handle_set_variable(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setVariable command."""
    return _handle_set_variable_impl(dbg, arguments)


def handle_evaluate(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle evaluate command."""
    return _handle_evaluate_impl(dbg, arguments)


def handle_set_data_breakpoints(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setDataBreakpoints command."""
    return _handle_set_data_breakpoints_impl(dbg, arguments)


def handle_data_breakpoint_info(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle dataBreakpointInfo command."""
    return _handle_data_breakpoint_info_impl(dbg, arguments)


def handle_exception_info(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle exceptionInfo command."""
    arguments = arguments or {}
    
    exception_info = {
        "exceptionId": "Exception",
        "description": "An exception occurred",
        "breakMode": "always",
        "details": {
            "message": "Exception details unavailable",
            "typeName": "Exception",
        }
    }
    
    if dbg:
        exc = getattr(dbg, "current_exception", None)
        if exc:
            try:
                exception_info.update({
                    "exceptionId": type(exc).__name__,
                    "description": str(exc),
                    "details": {
                        "message": str(exc),
                        "typeName": type(exc).__name__,
                    }
                })
            except Exception:
                pass
    
    return {"success": True, "body": exception_info}


def handle_configuration_done(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle configurationDone command."""
    return _handle_configuration_done_impl(_dbg, _arguments)


def handle_terminate(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle terminate command."""
    return _handle_terminate_impl(_dbg, _arguments)


def handle_initialize(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle initialize command."""
    return _handle_initialize_impl(_dbg, _arguments)


def handle_restart(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle restart command."""
    return _handle_restart_impl(_dbg, _arguments)


# =============================================================================
# Registered Handlers (decorated with @command_handler)
# These take only (arguments) and get dbg from state.debugger
# =============================================================================

@command_handler("setBreakpoints")
def _cmd_set_breakpoints(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_set_breakpoints_impl(dbg, arguments)


@command_handler("setFunctionBreakpoints")
def _cmd_set_function_breakpoints(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_set_function_breakpoints_impl(dbg, arguments)


@command_handler("setExceptionBreakpoints")
def _cmd_set_exception_breakpoints(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_set_exception_breakpoints_impl(dbg, arguments)


@command_handler("continue")
def _cmd_continue(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_continue_impl(dbg, arguments)


@command_handler("next")
def _cmd_next(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_next_impl(dbg, arguments)


@command_handler("stepIn")
def _cmd_step_in(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_step_in_impl(dbg, arguments)


@command_handler("stepOut")
def _cmd_step_out(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_step_out_impl(dbg, arguments)


@command_handler("pause")
def _cmd_pause(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_pause_impl(dbg, arguments)


@command_handler("stackTrace")
def _cmd_stack_trace(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_stack_trace_impl(dbg, arguments)


@command_handler("threads")
def _cmd_threads(arguments: dict[str, Any] | None = None) -> None:
    dbg = state.debugger
    if dbg:
        _handle_threads_impl(dbg, arguments)


@command_handler("scopes")
def _cmd_scopes(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_scopes_impl(dbg, arguments)


@command_handler("variables")
def _cmd_variables(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_variables_impl(dbg, arguments)


@command_handler("setVariable")
def _cmd_set_variable(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        result = _handle_set_variable_impl(dbg, arguments)
        if result:
            send_debug_message("setVariable", **result)


@command_handler("evaluate")
def _cmd_evaluate(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_evaluate_impl(dbg, arguments)


@command_handler("setDataBreakpoints")
def _cmd_set_data_breakpoints(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_set_data_breakpoints_impl(dbg, arguments)


@command_handler("dataBreakpointInfo")
def _cmd_data_breakpoint_info(arguments: dict[str, Any]) -> None:
    dbg = state.debugger
    if dbg:
        _handle_data_breakpoint_info_impl(dbg, arguments)


@command_handler("exceptionInfo")
def _cmd_exception_info(arguments: dict[str, Any]) -> None:
    """Handle exceptionInfo request."""
    thread_id = arguments.get("threadId") if arguments else None
    if thread_id is None:
        send_debug_message("error", message="Missing required argument 'threadId'")
        return
    dbg = state.debugger
    if not dbg:
        send_debug_message("error", message="Debugger not initialized")
        return
    if thread_id not in dbg.current_exception_info:
        send_debug_message("error", message=f"No exception info available for thread {thread_id}")
        return
    exception_info = dbg.current_exception_info[thread_id]
    send_debug_message(
        "exceptionInfo",
        exceptionId=exception_info["exceptionId"],
        description=exception_info["description"],
        breakMode=exception_info["breakMode"],
        details=exception_info["details"],
    )


@command_handler("configurationDone")
def _cmd_configuration_done(_arguments: dict[str, Any] | None = None) -> None:
    dbg = state.debugger
    _handle_configuration_done_impl(dbg, _arguments)


@command_handler("terminate")
def _cmd_terminate(_arguments: dict[str, Any] | None = None) -> None:
    dbg = state.debugger
    _handle_terminate_impl(dbg, _arguments)


@command_handler("initialize")
def _cmd_initialize(_arguments: dict[str, Any] | None = None) -> None:
    dbg = state.debugger
    result = _handle_initialize_impl(dbg, _arguments)
    if result:
        send_debug_message("response", **result)


@command_handler("restart")
def _cmd_restart(_arguments: dict[str, Any] | None = None) -> None:
    dbg = state.debugger
    _handle_restart_impl(dbg, _arguments)


@command_handler("loadedSources")
def _cmd_loaded_sources(_arguments: dict[str, Any] | None = None) -> None:
    """Handle loadedSources request to return all loaded source files."""
    
    seen_paths = set[str]()

    loaded_sources: list[Source] = []
    loaded_sources.extend(_collect_module_sources(seen_paths))
    loaded_sources.extend(_collect_linecache_sources(seen_paths))
    loaded_sources.extend(_collect_main_program_source(seen_paths))

    loaded_sources.sort(key=lambda s: s.get("name", ""))

    for s in loaded_sources:
        p = s.get("path")
        if not p:
            continue
        ref_id = state.get_ref_for_path(p) or state.get_or_create_source_ref(p, s.get("name"))
        s["sourceReference"] = ref_id

    send_debug_message("response", success=True, body={"sources": loaded_sources})


@command_handler("source")
def _cmd_source(arguments: dict[str, Any] | None = None) -> None:
    """Handle 'source' request to return source content."""
    if arguments is None:
        send_debug_message(
            "response", success=False, message="Missing arguments for source request"
        )
        return

    if (
        isinstance(arguments, dict)
        and "source" in arguments
        and isinstance(arguments["source"], dict)
    ):
        source = arguments["source"]
        source_reference = source.get("sourceReference")
        path = source.get("path")
    else:
        source = arguments
        source_reference = source.get("sourceReference")
        path = source.get("path")

    content = None
    mime_type: str | None = None

    if source_reference and isinstance(source_reference, int) and source_reference > 0:
        meta = state.get_source_meta(source_reference)
        if meta:
            path = meta.get("path") or path
        content = state.get_source_content_by_ref(source_reference)
    elif path:
        content = state.get_source_content_by_path(path)

    if content is not None and path and "\x00" not in content:
        guessed, _ = mimetypes.guess_type(path)
        if guessed:
            mime_type = guessed
        elif path.endswith((".py", ".pyw", ".txt", ".md")):
            mime_type = "text/plain; charset=utf-8"

    if content is None:
        send_debug_message("response", success=False, message="Could not load source content")
        return

    body: dict[str, Any] = {"content": content}
    if mime_type:
        body["mimeType"] = mime_type
    send_debug_message("response", success=True, body=body)


@command_handler("modules")
def _cmd_modules(arguments: dict[str, Any] | None = None) -> None:
    """Handle modules request to return loaded Python modules."""
    
    all_modules: list[Module] = []

    for module_name, module in sys.modules.items():
        if module is None:
            continue

        try:
            module_info: Module = {
                "id": module_name,
                "name": module_name,
            }

            module_file = getattr(module, "__file__", None)
            if module_file:
                module_path = Path(module_file).resolve()
                module_info["path"] = str(module_path)

                path_str = str(module_path)
                is_user_code = not any(
                    part in path_str.lower()
                    for part in ["site-packages", "lib/python", "lib\\python", "Lib"]
                )
                module_info["isUserCode"] = is_user_code

            if hasattr(module, "__version__"):
                module_info["version"] = str(module.__version__)

            all_modules.append(module_info)

        except (AttributeError, TypeError, OSError):
            continue

    all_modules.sort(key=lambda m: m["name"])

    if arguments:
        start_module = arguments.get("startModule", 0)
        module_count = arguments.get("moduleCount", 0)

        if module_count > 0:
            modules = all_modules[start_module : start_module + module_count]
        else:
            modules = all_modules[start_module:]
    else:
        modules = all_modules

    send_debug_message(
        "response", success=True, body={"modules": modules, "totalModules": len(all_modules)}
    )


# Expose for tests importing handle_loaded_sources directly
handle_loaded_sources = _cmd_loaded_sources
handle_source_cmd = _cmd_source
handle_modules = _cmd_modules

# Also expose single-argument versions of all handlers for tests
# that call them directly (instead of the two-argument versions above)
handle_set_breakpoints_cmd = _cmd_set_breakpoints
handle_set_function_breakpoints_cmd = _cmd_set_function_breakpoints
handle_set_exception_breakpoints_cmd = _cmd_set_exception_breakpoints
handle_continue_cmd = _cmd_continue
handle_next_cmd = _cmd_next
handle_step_in_cmd = _cmd_step_in
handle_step_out_cmd = _cmd_step_out
handle_pause_cmd = _cmd_pause
handle_stack_trace_cmd = _cmd_stack_trace
handle_threads_cmd = _cmd_threads
handle_scopes_cmd = _cmd_scopes
handle_variables_cmd = _cmd_variables
handle_set_variable_cmd = _cmd_set_variable
handle_evaluate_cmd = _cmd_evaluate
handle_set_data_breakpoints_cmd = _cmd_set_data_breakpoints
handle_data_breakpoint_info_cmd = _cmd_data_breakpoint_info
handle_exception_info_cmd = _cmd_exception_info
handle_configuration_done_cmd = _cmd_configuration_done
handle_terminate_cmd = _cmd_terminate
handle_initialize_cmd = _cmd_initialize
handle_restart_cmd = _cmd_restart
