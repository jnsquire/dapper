"""
Debug launcher for Python programs.
This is used to start the debuggee process with the debugger attached.
"""

from __future__ import annotations

import argparse
import ast
import bdb
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
from typing import Any
from typing import cast

from dapper.debug_helpers import frame_may_handle_exception
from dapper.debug_shared import state

"""
Debug launcher entry point. Delegates to split modules.
"""

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)

MAX_STRING_LENGTH = 1000
VAR_REF_TUPLE_SIZE = 2  # Variable references are stored as 2-element tuples


def send_debug_message(event_type: str, **kwargs) -> None:
    """
    Send a debug message to the debug adapter.
    These are prefixed with DBGP: to distinguish them from regular output.
    """
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled and state.ipc_wfile is not None:
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


def receive_debug_commands() -> None:
    """
    Listen for commands from the debug adapter on stdin.
    These are prefixed with DBGCMD: to distinguish them from regular input.
    """
    # read-only access to state.is_terminated
    if state.ipc_enabled and state.ipc_rfile is not None:
        reader = state.ipc_rfile
        while not state.is_terminated:
            line = reader.readline()
            if not line:
                os._exit(0)
            if line.startswith("DBGCMD:"):
                command_json = line[7:].strip()
                try:
                    command = json.loads(command_json)
                    with state.command_lock:
                        state.command_queue.append(command)
                    handle_debug_command(command)
                except Exception as e:
                    send_debug_message("error", message=f"Error receiving command: {e!s}")
                    traceback.print_exc()
    else:
        while not state.is_terminated:
            line = sys.stdin.readline()
            if not line:
                # End of input stream, debug adapter has closed connection
                os._exit(0)

            if line.startswith("DBGCMD:"):
                command_json = line[7:].strip()
                try:
                    command = json.loads(command_json)

                    with state.command_lock:
                        state.command_queue.append(command)

                    handle_debug_command(command)
                except Exception as e:
                    send_debug_message("error", message=f"Error receiving command: {e!s}")
                    traceback.print_exc()


def process_queued_commands():
    """Process any queued commands from the debug adapter"""
    # operate on the module state queue
    with state.command_lock:
        commands = state.command_queue.copy()
        state.command_queue.clear()

    for cmd in commands:
        handle_debug_command(cmd)


def handle_debug_command(command: dict[str, Any]) -> None:
    """Handle a debug command from the debug adapter"""
    # debugger is a module-global stored on state
    if state.debugger is None:
        # Queue commands until debugger is initialized
        return

    command_type = command.get("command", "")
    arguments = command.get("arguments", {})

    # Map command names to handler callables to reduce branching
    handlers: dict[str, Any] = {
        "setBreakpoints": handle_set_breakpoints,
        "setFunctionBreakpoints": handle_set_function_breakpoints,
        "setExceptionBreakpoints": handle_set_exception_breakpoints,
        "continue": handle_continue,
        "next": handle_next,
        "stepIn": handle_step_in,
        "stepOut": handle_step_out,
        "pause": handle_pause,
        "stackTrace": handle_stack_trace,
        "variables": handle_variables,
        "setVariable": handle_set_variable,
        "evaluate": handle_evaluate,
        "exceptionInfo": handle_exception_info,
        "configurationDone": lambda _: handle_configuration_done(),
        "terminate": lambda _: handle_terminate(),
    }

    handler = handlers.get(command_type)
    if handler is None:
        msg = f"Unsupported command: {command_type}"
        send_debug_message("error", message=msg)
        return

    try:
        result = handler(arguments)

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


def handle_set_breakpoints(arguments):
    """Handle setBreakpoints command"""
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")

    if path and state.debugger:
        # Clear existing breakpoints and metadata for this file
        state.debugger.clear_break(path)
        if hasattr(state.debugger, "clear_break_meta_for_file"):
            state.debugger.clear_break_meta_for_file(path)

        # Set new breakpoints and record metadata (hitCondition / logMessage)
        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            if line:
                # Set a BDB breakpoint; BDB enforces the 'condition'
                state.debugger.set_break(path, line, cond=condition)

                # Record DAP-specific metadata for runtime gating/logging
                if hasattr(state.debugger, "record_breakpoint"):
                    state.debugger.record_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                    )

        # Send response with verified breakpoints
        verified_bps = [{"verified": True, "line": bp.get("line")} for bp in bps]

        send_debug_message("breakpoints", source=source, breakpoints=verified_bps)


def handle_set_function_breakpoints(arguments):
    """Handle setFunctionBreakpoints command"""
    bps = arguments.get("breakpoints", [])

    if state.debugger:
        # Clear existing function breakpoints and associated metadata
        if hasattr(state.debugger, "clear_all_function_breakpoints"):
            state.debugger.clear_all_function_breakpoints()
        else:  # Fallback: reset structures if helper is unavailable
            state.debugger.function_breakpoints = []
            try:
                # Clear per-function metadata if available
                state.debugger.function_breakpoint_meta.clear()
            except Exception:
                pass

        # Set new function breakpoints and record their metadata
        for bp in bps:
            name = bp.get("name")
            if not name:
                continue

            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            # Some clients may send logMessage for function bps (non-standard)
            log_message = bp.get("logMessage")

            state.debugger.function_breakpoints.append(name)
            # Record DAP-style metadata if supported
            try:
                fbm = state.debugger.function_breakpoint_meta
            except Exception:
                fbm = None
            if isinstance(fbm, dict):
                mb = fbm.get(name, {})
                mb.setdefault("hit", 0)
                mb["condition"] = condition
                mb["hitCondition"] = hit_condition
                mb["logMessage"] = log_message
                fbm[name] = mb


def handle_set_exception_breakpoints(arguments):
    """Handle setExceptionBreakpoints command"""
    filters = arguments.get("filters", [])

    if state.debugger:
        # New boolean flags on debugger implementations
        try:
            state.debugger.exception_breakpoints_raised = "raised" in filters
            state.debugger.exception_breakpoints_uncaught = "uncaught" in filters
        except Exception:
            # If debugger doesn't expose boolean attrs, ignore silently
            pass


def handle_continue(arguments):
    """Handle continue command"""
    thread_id = arguments.get("threadId")

    dbg = state.debugger
    if dbg and thread_id in dbg.stopped_thread_ids:
        dbg.stopped_thread_ids.remove(thread_id)

        if not dbg.stopped_thread_ids:
            dbg.set_continue()


def handle_next(arguments):
    """Handle next command (step over)"""
    thread_id = arguments.get("threadId")

    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_next(dbg.current_frame)


def handle_step_in(arguments):
    """Handle stepIn command"""
    thread_id = arguments.get("threadId")

    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        dbg.set_step()


def handle_step_out(arguments):
    """Handle stepOut command"""
    thread_id = arguments.get("threadId")

    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_return(dbg.current_frame)


def handle_pause(arguments):
    """Handle pause command"""
    arguments.get("threadId")
    # This is tricky in Python - we can't easily interrupt a running thread.
    # A real implementation would use Python's settrace to handle this.


def handle_stack_trace(arguments):
    """Handle stackTrace command"""
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels", 0)

    dbg = state.debugger
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


def handle_variables(arguments):
    """Handle variables command"""
    var_ref = arguments.get("variablesReference")

    dbg = state.debugger
    if dbg and var_ref in dbg.var_refs:
        frame_info = dbg.var_refs[var_ref]

        if isinstance(frame_info, tuple):
            frame_id, scope = frame_info
            frame = dbg.frame_id_to_frame.get(frame_id)
            variables = []

            if frame and scope == "locals":
                for name, value in frame.f_locals.items():
                    # Create variable object for each local
                    var_obj = create_variable_object(name, value)
                    variables.append(var_obj)

            elif frame and scope == "globals":
                for name, value in frame.f_globals.items():
                    # Create variable object for each global
                    var_obj = create_variable_object(name, value)
                    variables.append(var_obj)

            send_debug_message("variables", variablesReference=var_ref, variables=variables)


def handle_set_variable(arguments):
    """Handle setVariable command with enhanced complex variable support"""
    var_ref = arguments.get("variablesReference")
    name = arguments.get("name")
    value = arguments.get("value")

    dbg = state.debugger
    if dbg and var_ref in dbg.var_refs:
        frame_info = dbg.var_refs[var_ref]

        # Variable references are stored as tuples with 2 elements
        if isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE:
            first, second = frame_info

            # Check if this is an object reference
            if first == "object":
                # This is an object reference, set attribute or item
                parent_obj = second
                return _set_object_member(parent_obj, name, value)
            # This is a scope reference (frame_id, scope_type)
            frame_id, scope = first, second
            frame = dbg.frame_id_to_frame.get(frame_id)

            if frame:
                return _set_scope_variable(frame, scope, name, value)

    # Invalid variable reference
    return {
        "success": False,
        "message": f"Invalid variable reference: {var_ref}",
    }


def _set_scope_variable(frame, scope, name, value):
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
        var_obj = create_variable_object(name, new_value)

        return {
            "success": True,
            "body": {
                "value": var_obj["value"],
                "type": var_obj["type"],
                "variablesReference": var_obj["variablesReference"],
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to set variable '{name}': {e!s}",
        }


def _set_object_member(parent_obj, name, value):
    """Set an attribute or item of an object"""
    try:
        # Enhanced value conversion with object context
        new_value = _convert_value_with_context(value, None, parent_obj)

        # Determine how to set the member based on the object type
        if isinstance(parent_obj, dict):
            # Dictionary - set item
            parent_obj[name] = new_value
        elif isinstance(parent_obj, list):
            # List - set by index
            try:
                index = int(name)
                if 0 <= index < len(parent_obj):
                    parent_obj[index] = new_value
                else:
                    return {
                        "success": False,
                        "message": f"List index {index} out of range",
                    }
            except ValueError:
                return {
                    "success": False,
                    "message": f"Invalid list index: {name}",
                }
        elif isinstance(parent_obj, tuple):
            # Tuples are immutable
            return {
                "success": False,
                "message": "Cannot modify tuple - tuples are immutable",
            }
        elif hasattr(parent_obj, name):
            # Generic object - set attribute
            setattr(parent_obj, name, new_value)
        else:
            # Try to set new attribute anyway (might be allowed)
            try:
                setattr(parent_obj, name, new_value)
            except (AttributeError, TypeError):
                return {
                    "success": False,
                    "message": (f"Cannot set attribute '{name}' on {type(parent_obj).__name__}"),
                }

        # Create variable object for the response
        var_obj = create_variable_object(name, new_value)

        return {
            "success": True,
            "body": {
                "value": var_obj["value"],
                "type": var_obj["type"],
                "variablesReference": var_obj["variablesReference"],
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


def create_variable_object(name, value):
    """Create a variable object for DAP"""

    # Create a simple representation of the value
    try:
        val_str = repr(value)
        if len(val_str) > MAX_STRING_LENGTH:
            val_str = val_str[:MAX_STRING_LENGTH] + "..."
    except Exception:
        val_str = "<Error getting value>"

    # Create a variable reference for complex objects
    var_ref = 0
    if hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple)):
        dbg = state.debugger
        if dbg is not None:
            var_ref = dbg.next_var_ref
            dbg.next_var_ref += 1
            dbg.var_refs[var_ref] = ("object", value)

    # Get type
    type_name = type(value).__name__

    return {
        "name": str(name),
        "value": val_str,
        "type": type_name,
        "variablesReference": var_ref,
    }


def handle_evaluate(arguments):
    """Handle evaluate command"""
    expression = arguments.get("expression")
    frame_id = arguments.get("frameId")
    arguments.get("context", "")

    result = "<evaluation not implemented>"
    var_ref = 0

    dbg = state.debugger
    if frame_id and dbg and frame_id in dbg.frame_id_to_frame:
        frame = dbg.frame_id_to_frame[frame_id]
        try:
            # Evaluate in frame's context
            value = eval(expression, frame.f_globals, frame.f_locals)
            result = repr(value)

            # Create variable reference if complex object
            if hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple)):
                var_ref = dbg.next_var_ref
                dbg.next_var_ref += 1
                dbg.var_refs[var_ref] = ("object", value)
        except Exception as e:
            result = f"<Error: {e!s}>"

    send_debug_message(
        "evaluate",
        expression=expression,
        result=result,
        variablesReference=var_ref,
    )


def handle_exception_info(arguments):
    """Handle exceptionInfo command"""
    thread_id = arguments.get("threadId")

    if thread_id is None:
        send_debug_message("error", message="Missing required argument 'threadId'")
        return

    dbg = state.debugger
    if not dbg:
        send_debug_message("error", message="Debugger not initialized")
        return

    # Get exception info for the thread
    if thread_id in dbg.current_exception_info:
        exception_info = dbg.current_exception_info[thread_id]
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


def handle_configuration_done():
    """Handle configurationDone command"""
    # Nothing to do here, just acknowledge


def handle_terminate():
    """Handle terminate command"""
    # Mark termination on the module state
    state.is_terminated = True
    send_debug_message("exited", exitCode=0)
    os._exit(0)


class DebuggerBDB(bdb.Bdb):
    """
    Custom BDB debugger implementation for the debug adapter
    """

    def __init__(self, skip=None):
        super().__init__(skip)
        self.is_terminated = False
        self.breakpoints = {}  # file_path -> list of breakpoints
        self.function_breakpoints = []  # list of function names
        # Function breakpoint metadata: name -> {condition, hitCondition,
        # logMessage, hit}
        self.function_breakpoint_meta = {}
        self.exception_breakpoints_uncaught = False
        self.exception_breakpoints_raised = False
        self.custom_breakpoints = {}  # filename -> {line: condition}
        self.current_thread_id = threading.get_ident()
        self.current_frame = None
        self.stepping = False
        self.stop_on_entry = False
        self.frames_by_thread = {}  # thread_id -> list of frames
        self.threads = {}  # thread_id -> thread name
        self.thread_ids = {}  # thread object -> thread_id
        self.thread_count = 1
        self.stopped_thread_ids = set()  # thread_ids that are currently stopped
        self.next_frame_id = 1
        self.frame_id_to_frame = {}  # frame_id -> frame object
        self.next_var_ref = 1000
        self.var_refs = {}  # var_ref -> (type, object) or (frame_id, scope)
        self.current_exception_info = {}  # thread_id -> exception details
        # Map (file_path, line) -> metadata: hit counter, hit/log conditions
        self.breakpoint_meta = {}

    # ---- Breakpoint metadata helpers ----
    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None:
        """Record DAP breakpoint metadata for gating/logging at runtime."""
        key = (path, int(line))
        meta = self.breakpoint_meta.get(key, {})
        meta.setdefault("hit", 0)
        meta["condition"] = condition
        meta["hitCondition"] = hit_condition
        meta["logMessage"] = log_message
        self.breakpoint_meta[key] = meta

    def clear_break_meta_for_file(self, path: str) -> None:
        """Remove any stored metadata for breakpoints in a given file."""
        to_del = [k for k in self.breakpoint_meta if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def user_line(self, frame):
        """Called when we hit a breakpoint or a step"""
        filename = frame.f_code.co_filename
        line = frame.f_lineno

        # If at a (file,line) breakpoint, apply DAP hitCondition/logMessage
        if self.get_break(filename, line) or (
            filename in self.custom_breakpoints and line in self.custom_breakpoints[filename]
        ):
            meta = self.breakpoint_meta.get((filename, int(line)))
            if meta is not None:
                # Increment hit counter and evaluate hitCondition gate
                meta["hit"] = int(meta.get("hit", 0)) + 1
                hc_expr = meta.get("hitCondition")
                if hc_expr and not _evaluate_hit_condition(str(hc_expr), meta["hit"]):
                    # Skip stopping/logging until the hit condition matches
                    self.set_continue()
                    return

                # Logpoints: if logMessage is set, emit output and continue
                log_msg = meta.get("logMessage")
                if log_msg:
                    try:
                        rendered = _format_log_message(str(log_msg), frame)
                    except Exception:
                        rendered = str(log_msg)
                    # Emit output event and continue without stopping
                    send_debug_message("output", category="console", output=str(rendered))
                    self.set_continue()
                    return

        # Get current thread
        thread_id = threading.get_ident()

        # Update thread info
        if thread_id not in self.threads:
            thread_name = threading.current_thread().name
            self.threads[thread_id] = thread_name

            # Send thread event
            send_debug_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )

        # Store current frame
        self.current_frame = frame

        # Update stopped thread info
        self.stopped_thread_ids.add(thread_id)

        # Calculate stack frames
        stack_frames = self._get_stack_frames(frame)
        self.frames_by_thread[thread_id] = stack_frames

        # Determine stop reason
        reason = "breakpoint"
        if self.stop_on_entry:
            reason = "entry"
            self.stop_on_entry = False
        elif self.stepping:
            reason = "step"
            self.stepping = False

        # Send stopped event
        send_debug_message(
            "stopped",
            threadId=thread_id,
            reason=reason,
            allThreadsStopped=True,
        )

        # Process any queued commands before we wait
        process_queued_commands()

        # Wait for continued command
        self.set_continue()

    def user_exception(self, frame, exc_info):
        """Called when an exception occurs"""
        # Only break on exception if configured
        if not (
            getattr(self, "exception_breakpoints_raised", False)
            or getattr(self, "exception_breakpoints_uncaught", False)
            or getattr(self, "exception_breakpoints", {}).get("raised")
            or getattr(self, "exception_breakpoints", {}).get("uncaught")
        ):
            return

        # Get exception info
        exc_type, exc_value, exc_traceback = exc_info

        # Use the module-level helper for detection (keeps this method small).

        # Conservative uncaught detection: inspect only the frame where the
        # exception was raised. This avoids helper frames used by tests
        # (which capture and re-raise) from masking whether the original
        # frame had an enclosing try/except. If detection cannot determine
        # handler presence (returns None), treat as possibly handled.
        is_uncaught = True
        res = frame_may_handle_exception(frame)
        # Keep the debug call within line-length limits by splitting args.
        logger.debug(
            "frame_may_handle_exception: frame=%r filename=%r",
            frame,
            getattr(frame.f_code, "co_filename", None),
        )
        logger.debug("lineno=%s -> %r", getattr(frame, "f_lineno", None), res)
        if res is True or res is None:
            is_uncaught = False

        # Get current thread
        thread_id = threading.get_ident()

        # Determine break mode and whether we should break
        try:
            break_mode = "always" if self.exception_breakpoints_raised else "unhandled"

            # Check if we should break
            if (
                is_uncaught and self.exception_breakpoints_uncaught
            ) or self.exception_breakpoints_raised:
                break_on_exception = True
            else:
                break_on_exception = False
        except Exception:
            # Fallback to dict-style if present
            break_mode = (
                "always"
                if getattr(self, "exception_breakpoints", {}).get("raised")
                else "unhandled"
            )
            if (
                is_uncaught and getattr(self, "exception_breakpoints", {}).get("uncaught")
            ) or getattr(self, "exception_breakpoints", {}).get("raised"):
                break_on_exception = True
            else:
                break_on_exception = False

        # Prepare stack trace (only used if we break and need details)
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)

        # Store exception details only if we will break on this exception.
        if break_on_exception:
            self.current_exception_info[thread_id] = {
                "exceptionId": exc_type.__name__,
                "description": str(exc_value),
                "breakMode": break_mode,
                "details": {
                    "message": str(exc_value),
                    "typeName": exc_type.__name__,
                    "fullTypeName": (exc_type.__module__ + "." + exc_type.__name__),
                    "source": frame.f_code.co_filename,
                    "stackTrace": stack_trace,
                },
            }

        if break_on_exception:
            # Store current frame
            self.current_frame = frame

            # Update stopped thread info
            self.stopped_thread_ids.add(thread_id)

            # Calculate stack frames
            stack_frames = self._get_stack_frames(frame)
            self.frames_by_thread[thread_id] = stack_frames

            # Send stopped event
            send_debug_message(
                "stopped",
                threadId=thread_id,
                reason="exception",
                text=f"{exc_type.__name__}: {exc_value!s}",
                allThreadsStopped=True,
            )

            # Process any queued commands before we wait
            process_queued_commands()

            # Wait for continued command
            try:
                self.set_continue()
            except Exception:
                _msg = "set_continue: call failed or debugger not fully initialized"
                logger.debug(_msg, exc_info=True)

    def _get_stack_frames(self, frame):
        """Get stack frames for the current frame"""
        stack_frames = []

        # Walk up the stack
        f = frame
        while f is not None:
            frame_id = self.next_frame_id
            self.next_frame_id += 1

            # Store frame for later reference
            self.frame_id_to_frame[frame_id] = f

            # Get source info
            filename = f.f_code.co_filename
            lineno = f.f_lineno

            # Create stack frame info
            stack_frame = {
                "id": frame_id,
                "name": f.f_code.co_name or "<unknown>",
                "line": lineno,
                "column": 0,  # We don't have column info
                "source": {
                    "name": Path(filename).name,
                    "path": filename,
                },
            }

            stack_frames.append(stack_frame)
            f = f.f_back

        return stack_frames

    def set_custom_breakpoint(self, filename: str, line: int, condition=None):
        """Set a breakpoint programmatically"""
        if filename not in self.custom_breakpoints:
            self.custom_breakpoints[filename] = {}
        self.custom_breakpoints[filename][line] = condition

        # Also set a real breakpoint using BDB's mechanism
        self.set_break(filename, line, cond=condition)

    def clear_custom_breakpoint(self, filename: str, line: int):
        """Clear a specific breakpoint"""
        if filename in self.custom_breakpoints and line in self.custom_breakpoints[filename]:
            del self.custom_breakpoints[filename][line]

            # Also clear from BDB
            self.clear_break(filename, line)

    def clear_all_custom_breakpoints(self):
        """Clear all custom breakpoints"""
        self.custom_breakpoints.clear()

    def clear_all_function_breakpoints(self):
        """Clear all function breakpoints and their metadata."""
        self.function_breakpoints = []
        self.function_breakpoint_meta.clear()

    def user_call(self, frame, argument_list):  # noqa: ARG002 - signature
        """Called when there is the 'call' event.

        Used to implement Function Breakpoints by matching the current call.
        """
        if not self.function_breakpoints and not self.function_breakpoint_meta:
            return

        # Build candidate names to match against configured function bps
        candidates = _get_function_candidate_names(frame)
        match_name = None
        for name in self.function_breakpoints:
            if name in candidates:
                match_name = name
                break

        if match_name is None:
            return

        meta = self.function_breakpoint_meta.get(match_name, {})

        # Increment hit count and apply hitCondition
        meta["hit"] = int(meta.get("hit", 0)) + 1
        hc_expr = meta.get("hitCondition")
        if hc_expr and not _evaluate_hit_condition(str(hc_expr), meta["hit"]):
            return

        # Evaluate condition if present
        cond = meta.get("condition")
        if cond:
            try:
                if not eval(cond, frame.f_globals, frame.f_locals):
                    return
            except Exception:
                # If condition evaluation fails, do not break
                return

        # Logpoint support for function bp
        log_msg = meta.get("logMessage")
        if log_msg:
            try:
                rendered = _format_log_message(str(log_msg), frame)
            except Exception:
                rendered = str(log_msg)
            send_debug_message("output", category="console", output=str(rendered))
            return

        # Stop here: mirror user_line stopping behavior
        thread_id = threading.get_ident()
        if thread_id not in self.threads:
            thread_name = threading.current_thread().name
            self.threads[thread_id] = thread_name
            send_debug_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )

        self.current_frame = frame
        self.stopped_thread_ids.add(thread_id)
        stack_frames = self._get_stack_frames(frame)
        self.frames_by_thread[thread_id] = stack_frames
        send_debug_message(
            "stopped",
            threadId=thread_id,
            reason="function breakpoint",
            allThreadsStopped=True,
        )
        process_queued_commands()
        self.set_continue()


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
    return parser.parse_args()


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
    if args.ipc:
        try:
            if args.ipc == "pipe" and os.name == "nt" and args.ipc_pipe:
                conn = _mpc.Client(address=args.ipc_pipe, family="AF_PIPE")
                state.ipc_enabled = True
                # Wrap with simple text protocol adapter

                class _PipeWriter:
                    def write(self, s: str) -> None:
                        conn.send(s)

                    def flush(self) -> None:
                        return

                    def close(self) -> None:
                        with contextlib.suppress(Exception):
                            conn.close()

                class _PipeReader:
                    def readline(self) -> str:
                        try:
                            data = conn.recv()
                        except (EOFError, OSError):
                            return ""
                        return cast("str", data)

                    def close(self) -> None:
                        with contextlib.suppress(Exception):
                            conn.close()

                state.ipc_rfile = _PipeReader()
                state.ipc_wfile = _PipeWriter()
            else:
                sock = None
                if args.ipc == "unix":
                    af_unix = getattr(socket, "AF_UNIX", None)
                    if af_unix and args.ipc_path:
                        sock = socket.socket(af_unix, socket.SOCK_STREAM)
                        sock.connect(args.ipc_path)
                else:
                    host = args.ipc_host or "127.0.0.1"
                    port = int(args.ipc_port)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.connect((host, port))
                if sock is not None:
                    state.ipc_sock = sock
                    state.ipc_rfile = sock.makefile("r", encoding="utf-8", newline="")
                    state.ipc_wfile = sock.makefile("w", encoding="utf-8", newline="")
                    state.ipc_enabled = True
        except Exception:
            # If IPC fails, proceed with stdio
            state.ipc_enabled = False

    # Start command listener thread (from IPC or stdin depending on state)
    command_thread = threading.Thread(target=receive_debug_commands, daemon=True)
    command_thread.start()

    # Create the debugger and store it on state
    state.debugger = DebuggerBDB()

    if state.stop_at_entry:
        state.debugger.stop_on_entry = True

    if state.no_debug:
        # Just run the program without debugging
        run_program(program_path, program_args)
    else:
        # Run the program with debugging
        sys.argv = [program_path, *program_args]
        state.debugger.run(f"exec(Path('{program_path}').open().read())")


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
