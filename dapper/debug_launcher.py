"""
Debug launcher for Python programs.
This is used to start the debuggee process with the debugger attached.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import logging
import os
import socket
import sys
import threading
import traceback
from multiprocessing import connection as _mpc
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper import debug_shared as _d_shared
from dapper.debug_shared import state
from dapper.debugger_bdb import DebuggerBDB
from dapper.ipc_binary import HEADER_SIZE
from dapper.ipc_binary import pack_frame
from dapper.ipc_binary import read_exact
from dapper.ipc_binary import unpack_header

if TYPE_CHECKING:
    from dapper.debugger_protocol import DebuggerLike
    from dapper.debugger_protocol import ExceptionInfo
    from dapper.debugger_protocol import Variable

    # Import protocol TypedDicts for stronger return typing
    from dapper.protocol_types import SetExceptionBreakpointsResponse
    from dapper.protocol_types import SetFunctionBreakpointsArguments

"""
Debug launcher entry point. Delegates to split modules.
"""

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)

MAX_STRING_LENGTH = 1000
VAR_REF_TUPLE_SIZE = 2  # Variable references are stored as 2-element tuples
SIMPLE_FN_ARGCOUNT = 2


def send_debug_message(event_type: str, **kwargs) -> None:
    """
    Send a debug message to the debug adapter.
    These are prefixed with DBGP: to distinguish them from regular output.
    """
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled:
        # Binary IPC when enabled
        if getattr(state, "ipc_binary", False):
            payload = json.dumps(message).encode("utf-8")
            frame = pack_frame(1, payload)
            # Prefer pipe conn if available
            conn = state.ipc_pipe_conn
            if conn is not None:
                conn.send_bytes(frame)

            wfile = state.ipc_wfile
            if wfile is not None:
                with contextlib.suppress(Exception):
                    wfile.write(frame)  # type: ignore[arg-type]
                    wfile.flush()  # type: ignore[call-arg]
                    return

        # Text IPC fallback
        if state.ipc_wfile is not None:
            try:
                state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
                state.ipc_wfile.flush()
            except Exception:
                # Fall back to logger
                pass
            else:
                return
    send_logger.debug(json.dumps(message))
    with contextlib.suppress(Exception):
        sys.stdout.flush()


KIND_EVENT = 1
KIND_COMMAND = 2


def _handle_command_bytes(payload: bytes) -> None:
    try:
        command = json.loads(payload.decode("utf-8"))
        state.command_queue.put(command)
        handle_debug_command(command)
    except Exception as e:
        send_debug_message("error", message=f"Error receiving command: {e!s}")
        traceback.print_exc()


def _recv_binary_from_pipe(conn: _mpc.Connection) -> None:
    while not state.is_terminated:
        try:
            data = conn.recv_bytes()
        except (EOFError, OSError):
            os._exit(0)
        if not data:
            os._exit(0)
        try:
            kind, length = unpack_header(data[:HEADER_SIZE])
        except Exception as e:
            send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = data[HEADER_SIZE:HEADER_SIZE + length]
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload)


def _recv_binary_from_stream(rfile: Any) -> None:
    while not state.is_terminated:
        header = read_exact(rfile, HEADER_SIZE)  # type: ignore[arg-type]
        if not header:
            os._exit(0)
        try:
            kind, length = unpack_header(header)
        except Exception as e:
            send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = read_exact(rfile, length)  # type: ignore[arg-type]
        if not payload:
            os._exit(0)
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload)


def receive_debug_commands() -> None:
    """
    Listen for commands from the debug adapter on stdin.
    These are prefixed with DBGCMD: to distinguish them from regular input.
    """
    # read-only access to state.is_terminated
    if state.ipc_enabled:
        # Binary IPC path
        conn = state.ipc_pipe_conn
        if conn is not None:
            _recv_binary_from_pipe(conn)
            return
        _recv_binary_from_stream(state.ipc_rfile)
        return

    while not state.is_terminated:
        line = sys.stdin.readline()
        if not line:
            # End of input stream, debug adapter has closed connection
            os._exit(0)

        if line.startswith("DBGCMD:"):
            _handle_command_bytes(line[7:].strip().encode("utf-8"))


def handle_debug_command(command: dict[str, Any]) -> None:
    """Handle a debug command from the debug adapter"""
    # debugger is a module-global stored on state
    if state.debugger is None:
        # Queue commands until debugger is initialized
        return

    # Pass the debugger instance explicitly to handlers
    dbg = state.debugger

    command_type = command.get("command", "")
    arguments = command.get("arguments", {})

    # Map command names to handler callables to reduce branching
    handlers: dict[str, Any] = {
        "setBreakpoints": handle_set_breakpoints,
        "initialize": handle_initialize,
        "setFunctionBreakpoints": handle_set_function_breakpoints,
        "setExceptionBreakpoints": handle_set_exception_breakpoints,
        "continue": handle_continue,
        "next": handle_next,
        "stepIn": handle_step_in,
        "stepOut": handle_step_out,
        "pause": handle_pause,
        "threads": handle_threads,
        "stackTrace": handle_stack_trace,
        "scopes": handle_scopes,
        "source": handle_source,
        "variables": handle_variables,
        "setVariable": handle_set_variable,
        "evaluate": handle_evaluate,
        "setDataBreakpoints": handle_set_data_breakpoints,
        "dataBreakpointInfo": handle_data_breakpoint_info,
        "exceptionInfo": handle_exception_info,
        "configurationDone": handle_configuration_done,
        "terminate": handle_terminate,
        "disconnect": handle_terminate,
        "restart": handle_restart,
    }

    handler = handlers.get(command_type)
    if handler is None:
        msg = f"Unsupported command: {command_type}"
        send_debug_message("error", message=msg)
        return

    try:
        result = handler(dbg, arguments)

        # If the handler returns a response dict, send it as a response
        if isinstance(result, dict) and "success" in result:
            command_id = command.get("id")
            if command_id is not None:
                response = {"id": command_id}
                response.update(result)
                send_debug_message("response", **response)

    except Exception as exc:  # pragma: no cover - defensive logging
        # Send error response if command had an ID
        command_id = command.get("id")
        if command_id is not None:
            msg = f"Error handling command {command_type}: {exc!s}"
            send_debug_message(
                "response",
                id=command_id,
                success=False,
                message=msg,
            )
        else:
            msg = f"Error handling command {command_type}: {exc!s}"
            send_debug_message("error", message=msg)
        traceback.print_exc()


def handle_set_breakpoints(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setBreakpoints command"""
    arguments = arguments or {}
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")

    if path and dbg:
        # Clear existing breakpoints and metadata for this file
        try:
            dbg.clear_breaks_for_file(path)  # type: ignore[attr-defined]
        except Exception:
            # Fallbacks for older implementations
            try:
                dbg.clear_break(path)  # type: ignore[misc]
            except Exception:
                try:
                    dbg.clear_break_meta_for_file(path)
                except Exception:
                    pass

        # Set new breakpoints and record metadata (hitCondition / logMessage)
        verified_bps: list[dict[str, Any]] = []
        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            verified = True
            if line:
                try:
                    # Some debugger implementations may return a boolean to
                    # indicate whether installing the breakpoint succeeded.
                    res = dbg.set_break(path, line, cond=condition)
                except Exception:
                    verified = False
                else:
                    # If the debugger explicitly returns False, treat the
                    # installation as unsuccessful. Treat True/None/other
                    # values as success for backward compatibility.
                    verified = res is not False

                # Record DAP-specific metadata for runtime gating/logging
                try:
                    dbg.record_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                    )
                except Exception:
                    # If recording metadata fails, continue silently
                    pass

            verified_bps.append({"verified": verified, "line": line})

        # Send response with verified breakpoints event for adapters
        send_debug_message("breakpoints", source=source, breakpoints=verified_bps)

        # Also return a response dict so handlers invoked via handle_debug_command
        # will produce a structured response when an id is present.
        return {"success": True, "body": {"breakpoints": verified_bps}}
    return None


def handle_set_function_breakpoints(dbg: DebuggerLike, arguments: SetFunctionBreakpointsArguments):
    """Handle setFunctionBreakpoints command"""
    arguments = arguments or {}
    bps = arguments.get("breakpoints", [])

    if dbg:
        # Clear existing function breakpoints and associated metadata
        dbg.clear_all_function_breakpoints()

        # Set new function breakpoints and record their metadata
        for bp in bps:
            name = bp.get("name")
            if not name:
                continue

            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            # Some clients may send logMessage for function bps (non-standard)
            log_message = bp.get("logMessage")

            dbg.function_breakpoints.append(name)
            # Record DAP-style metadata if supported
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

        # Build per-breakpoint verification results by checking whether
        # the debugger's function_breakpoints list contains the name.
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


def handle_set_exception_breakpoints(
    dbg: DebuggerLike, arguments: dict[str, Any]
) -> SetExceptionBreakpointsResponse | None:
    """Handle setExceptionBreakpoints command

    This function narrows the incoming `filters` value to a concrete
    list[str] before using it. That strengthens static typing and avoids
    passing ambiguous runtime values to the debugger.
    """
    arguments = arguments or {}
    raw_filters = arguments.get("filters", [])

    # Narrow to a list[str]. Accept list/tuple inputs and coerce elements
    # to strings. Any other shape becomes an empty list.
    if isinstance(raw_filters, (list, tuple)):
        filters: list[str] = [str(f) for f in raw_filters]
    else:
        filters = []

    if not dbg:
        return None

    # New boolean flags on debugger implementations. Try to set them and
    # return verification information per filter. If assignment fails,
    # mark all as unverified.
    verified_all: bool = True
    try:
        dbg.exception_breakpoints_raised = "raised" in filters
        dbg.exception_breakpoints_uncaught = "uncaught" in filters
    except Exception:
        verified_all = False

    body = {"breakpoints": [{"verified": verified_all} for _ in filters]}
    # Construct the response and cast it to the TypedDict declared in
    # protocol_types so the type checker can verify the return type.
    response: dict[str, Any] = {"success": True, "body": body}
    return cast("SetExceptionBreakpointsResponse", response)


def handle_continue(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle continue command"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id in dbg.stopped_thread_ids:
        dbg.stopped_thread_ids.remove(thread_id)

        if not dbg.stopped_thread_ids:
            dbg.set_continue()


def handle_next(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle next command (step over)"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_next(dbg.current_frame)


def handle_step_in(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepIn command"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        dbg.set_step()


def handle_step_out(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stepOut command"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_return(dbg.current_frame)


def handle_pause(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle pause command"""
    arguments = arguments or {}
    arguments.get("threadId")
    # This is tricky in Python - we can't easily interrupt a running thread.
    # A real implementation would use Python's settrace to handle this.


def handle_stack_trace(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle stackTrace command"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels", 0)

    if dbg and thread_id in dbg.frames_by_thread:
        frames = dbg.frames_by_thread[thread_id]
        total_frames = len(frames)

        # Apply startFrame and levels
        if levels > 0:
            end_frame = min(start_frame + levels, total_frames)
            frames_to_send = frames[start_frame:end_frame]
        else:
            frames_to_send = frames[start_frame:]

        send_debug_message(
            "stackTrace",
            threadId=thread_id,
            stackFrames=frames_to_send,
            totalFrames=total_frames,
        )


def handle_variables(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle variables command"""
    arguments = arguments or {}
    var_ref = arguments.get("variablesReference")

    if not (dbg and isinstance(var_ref, int) and var_ref in dbg.var_refs):
        return

    frame_info = dbg.var_refs[var_ref]
    variables: list[Variable] = []

    # Cached list of Variables is the simplest path
    if isinstance(frame_info, list):
        variables.extend([cast("Variable", v) for v in frame_info if isinstance(v, dict)])
        send_debug_message("variables", variablesReference=var_ref, variables=variables)
        return

    # Expect tuple form of (kind, payload)
    if not (isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE):
        send_debug_message("variables", variablesReference=var_ref, variables=variables)
        return

    kind, payload = frame_info

    if kind == "object":
        parent_obj = payload
        extract_variables(dbg, variables, parent_obj)
        send_debug_message("variables", variablesReference=var_ref, variables=variables)
        return

    if isinstance(kind, int) and payload in ("locals", "globals"):
        frame_id = kind
        scope = payload
        frame = dbg.frame_id_to_frame.get(frame_id)
        if not frame:
            send_debug_message("variables", variablesReference=var_ref, variables=variables)
            return

        mapping = frame.f_locals if scope == "locals" else frame.f_globals
        for name, val in mapping.items():
            var_obj = dbg.make_variable_object(name, val, frame) if dbg else None
            if var_obj:
                variables.append(cast("Variable", var_obj))
            else:
                variables.append(_d_shared.make_variable_object(name, val, dbg, frame))
        send_debug_message("variables", variablesReference=var_ref, variables=variables)
        return

    # Fallback: respond with what we have
    send_debug_message("variables", variablesReference=var_ref, variables=variables)


def extract_variables(dbg, variables, parent_obj):
    if isinstance(parent_obj, dict):
        for name, val in parent_obj.items():
            var_obj = dbg.make_variable_object(name, val) if dbg else None
            variables.append(
                cast("Variable", var_obj)
                if var_obj
                else _d_shared.make_variable_object(name, val, dbg)
            )
    elif isinstance(parent_obj, list):
        for idx, val in enumerate(parent_obj):
            name = str(idx)
            var_obj = dbg.make_variable_object(name, val) if dbg else None
            variables.append(
                cast("Variable", var_obj)
                if var_obj
                else _d_shared.make_variable_object(name, val, dbg)
            )
    else:
        for name in dir(parent_obj):
            if name.startswith("_"):
                continue
            try:
                val = getattr(parent_obj, name)
            except Exception:
                continue
            if dbg:
                variables.append(dbg.make_variable_object(name, val))
            else:
                variables.append(_d_shared.make_variable_object(name, val, dbg))


def handle_set_variable(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setVariable command with enhanced complex variable support"""
    arguments = arguments or {}
    var_ref = arguments.get("variablesReference")
    name = arguments.get("name")
    value = arguments.get("value")

    if dbg and isinstance(var_ref, int) and var_ref in dbg.var_refs:
        frame_info = dbg.var_refs[var_ref]

        # Handle tuple forms explicitly to narrow to object vs scope refs
        if isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE:
            first, second = frame_info

            # object reference
            if first == "object":
                parent_obj = second
                return _set_object_member(parent_obj, name, value)

            # scope reference
            if isinstance(first, int) and second in ("locals", "globals"):
                # Narrow to int for the type checker
                assert isinstance(first, int)
                frame_id: int = first
                scope: str = second
                frame = dbg.frame_id_to_frame.get(frame_id)
                if frame:
                    return _set_scope_variable(frame, scope, cast("Any", name), cast("Any", value))

    # Invalid variable reference
    return {
        "success": False,
        "message": f"Invalid variable reference: {var_ref}",
    }


def _set_scope_variable(frame, scope: str, name: Any, value: Any):
    """Set a variable in a frame scope (locals or globals)"""
    try:
        # Enhanced value conversion with frame context
        new_value = _convert_value_with_context(value, frame)

        # Set the variable in the appropriate scope
        if scope == "locals":
            frame.f_locals[name] = new_value
        elif scope == "globals":
            frame.f_globals[name] = new_value
        else:
            return {"success": False, "message": f"Unknown scope: {scope}"}

        # Create variable object for the response
        dbg = state.debugger
        fn = getattr(dbg, "make_variable_object", None) if dbg is not None else None
        var_obj = None
        if callable(fn):
            try:
                # Some debuggers may accept (name, value) or (name, value, frame)
                if (
                    getattr(fn, "__code__", None) is not None
                    and fn.__code__.co_argcount > SIMPLE_FN_ARGCOUNT
                ):
                    var_obj = fn(name, new_value, frame)
                else:
                    var_obj = fn(name, new_value)
            except Exception:
                var_obj = None

        # Only accept mapping-like results from debugger helper
        if not isinstance(var_obj, dict):
            var_obj = None

        if not var_obj:
            var_obj = _d_shared.make_variable_object(name, new_value, dbg, frame)

        var_obj = cast("Variable", var_obj)
        return {
            "success": True,
            "body": {
                "value": cast("dict", var_obj)["value"],
                "type": cast("dict", var_obj)["type"],
                "variablesReference": cast("dict", var_obj)["variablesReference"],
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to set variable '{name}': {e!s}",
        }


def _set_object_member(parent_obj, name, value):
    """Set an attribute or item of an object using a consolidated dispatch and single error path."""
    try:
        new_value = _convert_value_with_context(value, None, parent_obj)

        # Dispatch handlers for supported container types
        if isinstance(parent_obj, dict):
            parent_obj[name] = new_value
        elif isinstance(parent_obj, list):
            # validate and assign list index
            try:
                index = int(name)
            except Exception:
                return {"success": False, "message": f"Invalid list index: {name}"}
            if not (0 <= index < len(parent_obj)):
                return {"success": False, "message": f"List index {index} out of range"}
            parent_obj[index] = new_value
        elif isinstance(parent_obj, tuple):
            return {"success": False, "message": "Cannot modify tuple - tuples are immutable"}
        else:
            # attempt attribute assignment once
            try:
                setattr(parent_obj, name, new_value)
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Cannot set attribute '{name}' on {type(parent_obj).__name__}: {e!s}",
                }

        # Build variable object for response with a single fallback path
        dbg = state.debugger
        fn = getattr(dbg, "make_variable_object", None) if dbg is not None else None
        var_obj = None
        if callable(fn):
            try:
                candidate = fn(name, new_value)
                if isinstance(candidate, dict):
                    var_obj = candidate
            except Exception:
                var_obj = None

        if not isinstance(var_obj, dict):
            var_obj = _d_shared.make_variable_object(name, new_value, dbg, None)

        var_obj = cast("Variable", var_obj)
        return {
            "success": True,
            "body": {
                "value": cast("dict", var_obj)["value"],
                "type": cast("dict", var_obj)["type"],
                "variablesReference": cast("dict", var_obj)["variablesReference"],
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to set object member '{name}': {e!s}",
        }


def _convert_value_with_context(value_str: str, frame=None, parent_obj=None):
    """
    Enhanced value conversion with context awareness.

    Args:
        value_str: String representation of the value
        frame: Optional frame for evaluating expressions in context
        parent_obj: Optional parent object for type inference
    """
    # Strip whitespace
    value_str = value_str.strip()

    # Handle special values
    if value_str.lower() == "none":
        return None
    if value_str.lower() in ("true", "false"):
        return value_str.lower() == "true"

    # Try to evaluate as a Python literal first (safest)
    try:
        return ast.literal_eval(value_str)
    except (ValueError, SyntaxError):
        pass

    # If we have a frame, try to evaluate as an expression
    if frame is not None:
        try:
            return eval(value_str, frame.f_globals, frame.f_locals)
        except Exception:
            pass  # Fall through to other methods

    # Type inference based on parent object
    if parent_obj is not None:
        try:
            target_type = None
            if isinstance(parent_obj, list) and len(parent_obj) > 0:
                target_type = type(parent_obj[0])
            elif isinstance(parent_obj, dict) and parent_obj:
                sample_value = next(iter(parent_obj.values()))
                target_type = type(sample_value)

            if target_type in (int, float, bool, str):
                return target_type(value_str)
        except (ValueError, TypeError):
            pass  # Fall through to string

    # Default: treat as string
    return value_str


def _convert_string_to_value(value_str: str):
    """Convert a string representation to appropriate Python value"""
    # Keep the original function for backward compatibility
    return _convert_value_with_context(value_str)


# create_variable_object removed: use debug_shared.make_variable_object instead


def handle_evaluate(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle evaluate command"""
    arguments = arguments or {}
    expression = arguments.get("expression")
    frame_id = arguments.get("frameId")
    arguments.get("context", "")

    result = "<evaluation not implemented>"
    var_ref = 0

    if frame_id and dbg and frame_id in dbg.frame_id_to_frame:
        # Evaluate in frame's context only if we have a string expression
        if isinstance(expression, str):
            try:
                frame = dbg.frame_id_to_frame[frame_id]
                value = eval(expression, frame.f_globals, frame.f_locals)
                result = repr(value)

                # Create variable reference if complex object
                if hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple)):
                    var_ref = dbg.next_var_ref
                    dbg.next_var_ref += 1
                    dbg.var_refs[var_ref] = ("object", value)
            except Exception as e:
                result = f"<Error: {e!s}>"
        else:
            _msg = "expression must be a string"
            raise TypeError(_msg)

    send_debug_message(
        "evaluate",
        expression=expression,
        result=result,
        variablesReference=var_ref,
    )


def handle_exception_info(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle exceptionInfo command"""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if thread_id is None:
        send_debug_message("error", message="Missing required argument 'threadId'")
        return

    if not dbg:
        send_debug_message("error", message="Debugger not initialized")
        return

    # Get exception info for the thread
    if thread_id in dbg.current_exception_info:
        exception_info: ExceptionInfo = dbg.current_exception_info[thread_id]
        # Structure matches ExceptionInfoResponseBody
        send_debug_message(
            "exceptionInfo",
            exceptionId=exception_info["exceptionId"],
            description=exception_info["description"],
            breakMode=exception_info["breakMode"],
            details=exception_info["details"],
        )
    else:
        send_debug_message(
            "error",
            message=f"No exception info available for thread {thread_id}",
        )


def handle_configuration_done(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle configurationDone command"""
    # Nothing to do here, just acknowledge


def handle_terminate(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle terminate command"""
    # Mark termination on the module state
    state.is_terminated = True
    send_debug_message("exited", exitCode=0)
    os._exit(0)


def handle_initialize(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle initialize command (minimal capabilities response)."""
    # Return a conservative set of capabilities the debuggee can support.
    caps = {
        "supportsConfigurationDoneRequest": True,
        "supportsEvaluateForHovers": True,
        "supportsSetVariable": True,
        "supportsRestartRequest": False,
    }
    return {"success": True, "body": caps}


def handle_threads(dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Handle threads request: return current threads list."""
    threads_list = []
    if dbg:
        for tid, name in getattr(dbg, "threads", {}).items():
            threads_list.append({"id": tid, "name": name})

    return {"success": True, "body": {"threads": threads_list}}


def handle_scopes(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle scopes request for a given frameId.

    This returns locals and globals scopes with variablesReference ids set up
    so the existing `handle_variables` can be used to fetch them.
    """
    frame_id = arguments.get("frameId")
    if not dbg or frame_id not in dbg.frame_id_to_frame:
        return {"success": False, "message": "Invalid frameId"}

    # Create two variable references: locals and globals
    locals_ref = dbg.next_var_ref
    dbg.next_var_ref += 1
    dbg.var_refs[locals_ref] = (frame_id, "locals")

    globals_ref = dbg.next_var_ref
    dbg.next_var_ref += 1
    dbg.var_refs[globals_ref] = (frame_id, "globals")

    scopes = [
        {"name": "Locals", "variablesReference": locals_ref, "expensive": False},
        {"name": "Globals", "variablesReference": globals_ref, "expensive": False},
    ]

    return {"success": True, "body": {"scopes": scopes}}


def handle_source(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle source request: return file contents for a given source path."""
    arguments = arguments or {}
    source = arguments.get("source") or {}
    path = source.get("path") or arguments.get("path")
    if not path:
        return {"success": False, "message": "Missing source path"}

    try:
        with Path(path).open("r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"success": False, "message": f"Failed to read source: {e!s}"}

    return {"success": True, "body": {"content": content}}


def handle_set_data_breakpoints(dbg: DebuggerLike, arguments: dict[str, Any]):
    """Handle setDataBreakpoints (minimal support).

    Stores a list of configured data breakpoints on the debugger instance.
    """
    arguments = arguments or {}
    bps = arguments.get("breakpoints", [])
    if dbg is not None:
        try:
            dbg.data_breakpoints = bps
        except Exception:
            pass

    # Return verified list (conservative: mark all as verified=False if none)
    verified = [{"verified": True, "id": bp.get("dataId") or bp.get("name")} for bp in bps]

    return {"success": True, "body": {"breakpoints": verified}}


def handle_data_breakpoint_info(_dbg: DebuggerLike, arguments: dict[str, Any]):
    """Return minimal info about a data breakpoint target."""
    arguments = arguments or {}
    name = arguments.get("name")
    if not name:
        return {"success": False, "message": "Missing name"}

    # Minimal response: say we can set a breakpoint but cannot persist it
    return {"success": True, "body": {"dataId": name, "canPersist": False}}


def handle_restart(_dbg: DebuggerLike, _arguments: dict[str, Any] | None = None):
    """Attempt to restart the debuggee process.

    This implementation attempts to re-exec the current Python interpreter with
    the same arguments. If re-exec fails, returns an error response. Note: this
    will replace the current process image and not return on success.
    """
    # If no debugger/state, can't safely restart
    try:
        # Build argv from original sys.argv if possible
        argv = list(sys.argv)
        python = sys.executable or "python"

        # Acknowledge the restart request before re-exec so the adapter can
        # proceed. We mark termination to allow any other threads to observe.
        state.is_terminated = True
        send_debug_message("exited", exitCode=0)

        # Perform exec - on success this does not return
        os.execv(python, [python, *argv])
    except Exception as e:
        # If exec failed, return error response to adapter
        return {"success": False, "message": f"Restart failed: {e!s}"}


def _get_function_candidate_names(frame) -> set[str]:
    """Return a set of names that can match a function breakpoint.

    Includes plain function name, module-qualified name, and class-qualified
    name for methods when possible.
    """
    names: set[str] = set()
    code = getattr(frame, "f_code", None)
    if not code:
        return names

    func = getattr(code, "co_name", None) or ""
    mod = frame.f_globals.get("__name__", "")
    names.add(func)
    if mod:
        names.add(f"{mod}.{func}")

    # Detect bound method: f_locals may have 'self'
    self_obj = frame.f_locals.get("self") if isinstance(frame.f_locals, dict) else None
    if self_obj is not None:
        cls = getattr(self_obj, "__class__", None)
        cls_name = getattr(cls, "__name__", None)
        if cls_name:
            names.add(f"{cls_name}.{func}")
            if mod:
                names.add(f"{mod}.{cls_name}.{func}")

    return names


# ---- Helpers for DAP breakpoint features ----


def _evaluate_hit_condition(expr: str, hit_count: int) -> bool:
    """Evaluate DAP hitCondition against current hit_count.

    Supported forms (space tolerant):
    - "10"     -> hit_count == 10
    - "== 10"  -> hit_count == 10
    - ">= 10"  -> hit_count >= 10
    - "% 5"   -> hit_count % 5 == 0
    On parse error, return True (do not block).
    """
    try:
        import re as _re  # noqa: PLC0415 - local import

        s = expr.strip()
        # % N -> multiples of N
        m = _re.match(r"^%\s*(\d+)$", s)
        if m:
            n = int(m.group(1))
            return n > 0 and (hit_count % n == 0)

        # == N
        m = _re.match(r"^==\s*(\d+)$", s)
        if m:
            return hit_count == int(m.group(1))

        # >= N
        m = _re.match(r"^>=\s*(\d+)$", s)
        if m:
            return hit_count >= int(m.group(1))

        # Plain integer -> equal to N
        if _re.match(r"^\d+$", s):
            return hit_count == int(s)
    except Exception:
        return True
    # Fallback: allow break by default when expression didn't match
    return True


def _format_log_message(template: str, frame) -> str:
    """Render a logMessage by replacing {expr} with evaluated expressions.

    Example: "x={x}, sum={a+b}". Errors are replaced with <error>.
    """
    import re as _re  # noqa: PLC0415 - local import

    # Pattern matches either escaped {{literal}} or an expression {expr}
    pattern = _re.compile(r"\{\{([^{}]+)\}\}|\{([^{}]+)\}")

    def repl(match):
        literal = match.group(1)
        expr = match.group(2)
        if literal is not None:
            # Escaped braces -> return literal text inside braces
            return "{" + literal + "}"
        if expr is not None:
            try:
                val = eval(expr, frame.f_globals, frame.f_locals)
                return str(val)
            except Exception:
                return "<error>"
        return match.group(0)

    return pattern.sub(repl, template)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Python Debug Launcher")
    parser.add_argument(
        "--program",
        type=str,
        required=True,
        help="Path to the Python program to debug",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Arguments to pass to the debugged program",
    )
    parser.add_argument(
        "--stop-on-entry",
        action="store_true",
        help="Stop at the entry point of the program",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Run the program without debugging",
    )
    parser.add_argument(
        "--ipc",
        choices=["tcp", "unix", "pipe"],
        help=(
            "Optional IPC transport type to connect back to the adapter. "
            "On Windows use 'tcp' or 'pipe'."
        ),
    )
    parser.add_argument("--ipc-host", type=str, help="IPC TCP host")
    parser.add_argument("--ipc-port", type=int, help="IPC TCP port")
    parser.add_argument("--ipc-path", type=str, help="IPC UNIX socket path")
    parser.add_argument("--ipc-pipe", type=str, help="IPC Windows pipe name")
    parser.add_argument("--ipc-binary", action="store_true", help="Use binary IPC frames")
    return parser.parse_args()


def _setup_ipc_pipe(ipc_pipe: str | None) -> None:
    """Initialize Windows named pipe IPC.

    On success, populates state.ipc_* fields and enables IPC. On failure, raises.
    """
    if not (os.name == "nt" and ipc_pipe):
        msg = "Pipe IPC requested but not on Windows or missing pipe name"
        raise RuntimeError(msg)

    conn = _mpc.Client(address=ipc_pipe, family="AF_PIPE")
    state.ipc_enabled = True
    state.ipc_pipe_conn = conn


def _setup_ipc_socket(
    kind: str,
    host: str | None,
    port: int | None,
    path: str | None,
    ipc_binary: bool = False,
) -> None:
    """Initialize TCP/UNIX socket IPC and configure state.

    kind: "tcp" or "unix"
    """
    sock = None
    if kind == "unix":
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix and path:
            sock = socket.socket(af_unix, socket.SOCK_STREAM)
            sock.connect(path)
        else:
            msg = "UNIX sockets unsupported or missing path"
            raise RuntimeError(msg)
    else:
        # Default to TCP
        if port is None:
            msg = "Missing --ipc-port for TCP IPC"
            raise RuntimeError(msg)
        h = host or "127.0.0.1"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((h, int(port)))

    state.ipc_sock = sock
    state.ipc_rfile = cast("Any", sock.makefile("rb", buffering=0))
    state.ipc_wfile = cast("Any", sock.makefile("wb", buffering=0))
    state.ipc_enabled = True
    # record whether binary frames are used
    state.ipc_binary = bool(ipc_binary)


def setup_ipc_from_args(args: Any) -> None:
    """Best-effort IPC initialization based on parsed CLI args.

    Any failure will leave IPC disabled and fall back to stdio.
    """
    if not args.ipc:
        return
    try:
        if args.ipc == "pipe":
            _setup_ipc_pipe(args.ipc_pipe)
        else:
            _setup_ipc_socket(
                args.ipc, args.ipc_host, args.ipc_port, args.ipc_path, args.ipc_binary
            )
    except Exception:
        # If IPC fails, proceed with stdio
        state.ipc_enabled = False


def start_command_listener() -> threading.Thread:
    """Start the background thread that listens for incoming commands."""
    thread = threading.Thread(target=receive_debug_commands, daemon=True)
    thread.start()
    return thread


def configure_debugger(stop_on_entry: bool) -> DebuggerBDB:
    """Create and configure the debugger, storing it on shared state."""
    dbg = DebuggerBDB()
    if stop_on_entry:
        dbg.stop_on_entry = True
    state.debugger = dbg
    return dbg


def run_with_debugger(program_path: str, program_args: list[str]) -> None:
    """Execute the target program under the debugger instance in state."""
    sys.argv = [program_path, *program_args]
    dbg = state.debugger
    if dbg is None:
        dbg = configure_debugger(False)
    dbg.run(f"exec(Path('{program_path}').open().read())")


def main():
    """Main entry point for the debug launcher"""
    # Parse arguments and set module state
    args = parse_args()
    program_path = args.program
    program_args = args.arg
    state.stop_at_entry = args.stop_on_entry
    state.no_debug = args.no_debug

    # Configure logging for debug messages
    logging.basicConfig(level=logging.DEBUG, format="DEBUG: %(message)s")

    # Establish IPC connection if requested
    setup_ipc_from_args(args)

    # Start command listener thread (from IPC or stdin depending on state)
    start_command_listener()

    # Create the debugger and store it on state
    configure_debugger(state.stop_at_entry)

    if state.no_debug:
        # Just run the program without debugging
        run_program(program_path, program_args)
    else:
        # Run the program with debugging
        run_with_debugger(program_path, program_args)


def run_program(program_path, args):
    """Run the program without debugging"""
    sys.argv = [program_path, *args]

    with Path(program_path).open() as f:
        program_code = f.read()

    # Add the program directory to sys.path
    program_dir = Path(program_path).resolve().parent
    if str(program_dir) not in sys.path:
        sys.path.insert(0, str(program_dir))

    # Execute the program
    exec(program_code, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
