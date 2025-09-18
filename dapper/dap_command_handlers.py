"""
DAP command handler functions for debug launcher.
"""

from __future__ import annotations

import ast
import linecache
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from dapper.debug_shared import MAX_STRING_LENGTH
from dapper.debug_shared import VAR_REF_TUPLE_SIZE
from dapper.debug_shared import send_debug_message
from dapper.debug_shared import state
from dapper.protocol_types import Source

if TYPE_CHECKING:
    from dapper.protocol_types import ConfigurationDoneArguments
    from dapper.protocol_types import ContinueArguments
    from dapper.protocol_types import EvaluateArguments
    from dapper.protocol_types import ExceptionInfoArguments
    from dapper.protocol_types import LoadedSourcesRequest
    from dapper.protocol_types import Module
    from dapper.protocol_types import ModulesArguments
    from dapper.protocol_types import NextArguments
    from dapper.protocol_types import PauseArguments
    from dapper.protocol_types import SetBreakpointsArguments
    from dapper.protocol_types import SetExceptionBreakpointsArguments
    from dapper.protocol_types import SetFunctionBreakpointsArguments
    from dapper.protocol_types import SetVariableArguments
    from dapper.protocol_types import StackTraceArguments
    from dapper.protocol_types import StepInArguments
    from dapper.protocol_types import StepOutArguments
    from dapper.protocol_types import TerminateArguments
    from dapper.protocol_types import VariablesArguments


# Command mapping table - will be populated by the @command_handler decorator
COMMAND_HANDLERS = {}


def command_handler(command_name):
    """Decorator to register DAP command handlers."""

    def decorator(func):
        COMMAND_HANDLERS[command_name] = func
        return func

    return decorator


def handle_debug_command(command: dict[str, Any]) -> None:
    """Handle debug commands using a mapping table for better maintainability."""
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


@command_handler("setBreakpoints")
def handle_set_breakpoints(arguments: SetBreakpointsArguments) -> None:
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")
    if path and state.debugger:
        state.debugger.clear_break(path)
        if hasattr(state.debugger, "clear_break_meta_for_file"):
            state.debugger.clear_break_meta_for_file(path)
        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")
            if line:
                state.debugger.set_break(path, line, cond=condition)
                if hasattr(state.debugger, "record_breakpoint"):
                    state.debugger.record_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                    )
        verified_bps = [{"verified": True, "line": bp.get("line")} for bp in bps]
        send_debug_message(
            "breakpoints",
            source=source,
            breakpoints=verified_bps,
        )


@command_handler("setFunctionBreakpoints")
def handle_set_function_breakpoints(arguments: SetFunctionBreakpointsArguments) -> None:
    bps = arguments.get("breakpoints", [])
    if state.debugger:
        if hasattr(state.debugger, "clear_all_function_breakpoints"):
            state.debugger.clear_all_function_breakpoints()
        else:
            state.debugger.function_breakpoints = []
            try:
                state.debugger.function_breakpoint_meta.clear()
            except Exception:
                pass
        for bp in bps:
            name = bp.get("name")
            if not name:
                continue
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")
            state.debugger.function_breakpoints.append(name)
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


@command_handler("setExceptionBreakpoints")
def handle_set_exception_breakpoints(arguments: SetExceptionBreakpointsArguments) -> None:
    filters = arguments.get("filters", [])
    if state.debugger:
        state.debugger.exception_breakpoints_raised = "raised" in filters
        state.debugger.exception_breakpoints_uncaught = "uncaught" in filters


@command_handler("continue")
def handle_continue(arguments: ContinueArguments) -> None:
    thread_id = arguments.get("threadId")
    dbg = state.debugger
    if dbg and thread_id in dbg.stopped_thread_ids:
        dbg.stopped_thread_ids.remove(thread_id)
        if not dbg.stopped_thread_ids:
            dbg.set_continue()


@command_handler("next")
def handle_next(arguments: NextArguments) -> None:
    thread_id = arguments.get("threadId")
    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_next(dbg.current_frame)


@command_handler("stepIn")
def handle_step_in(arguments: StepInArguments) -> None:
    thread_id = arguments.get("threadId")
    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        dbg.set_step()


@command_handler("stepOut")
def handle_step_out(arguments: StepOutArguments) -> None:
    thread_id = arguments.get("threadId")
    dbg = state.debugger
    if dbg and thread_id == threading.get_ident():
        dbg.stepping = True
        if dbg.current_frame is not None:
            dbg.set_return(dbg.current_frame)


@command_handler("pause")
def handle_pause(arguments: PauseArguments) -> None:
    arguments.get("threadId")
    # Not implemented


@command_handler("stackTrace")
def handle_stack_trace(arguments: StackTraceArguments) -> None:
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels", 0)
    dbg = state.debugger
    if dbg and thread_id in dbg.frames_by_thread:
        frames = dbg.frames_by_thread[thread_id]
        total_frames = len(frames)
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


@command_handler("variables")
def handle_variables(arguments: VariablesArguments) -> None:
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
                    var_obj = create_variable_object(name, value)
                    variables.append(var_obj)
            elif frame and scope == "globals":
                for name, value in frame.f_globals.items():
                    var_obj = create_variable_object(name, value)
                    variables.append(var_obj)
            send_debug_message(
                "variables",
                variablesReference=var_ref,
                variables=variables,
            )


@command_handler("setVariable")
def handle_set_variable(arguments: SetVariableArguments) -> None:
    var_ref = arguments.get("variablesReference")
    name = arguments.get("name")
    value = arguments.get("value")
    dbg = state.debugger
    if dbg and var_ref in dbg.var_refs:
        frame_info = dbg.var_refs[var_ref]
        if isinstance(frame_info, tuple) and len(frame_info) == VAR_REF_TUPLE_SIZE:
            first, second = frame_info
            if first == "object":
                parent_obj = second
                result = _set_object_member(parent_obj, name, value)
                send_debug_message("setVariable", **result)
                return
            frame_id, scope = first, second
            frame = dbg.frame_id_to_frame.get(frame_id)
            if frame:
                result = _set_scope_variable(frame, scope, name, value)
                send_debug_message("setVariable", **result)
                return
    send_debug_message(
        "setVariable", success=False, message=f"Invalid variable reference: {var_ref}"
    )


def _set_scope_variable(frame, scope, name, value):
    try:
        new_value = _convert_value_with_context(value, frame)
        if scope == "locals":
            frame.f_locals[name] = new_value
        elif scope == "globals":
            frame.f_globals[name] = new_value
        else:
            return {"success": False, "message": f"Unknown scope: {scope}"}
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
    try:
        new_value = _convert_value_with_context(value, None, parent_obj)
        if isinstance(parent_obj, dict):
            parent_obj[name] = new_value
        elif isinstance(parent_obj, list):
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
            return {
                "success": False,
                "message": "Cannot modify tuple - tuples are immutable",
            }
        elif hasattr(parent_obj, name):
            setattr(parent_obj, name, new_value)
        else:
            try:
                setattr(parent_obj, name, new_value)
            except (AttributeError, TypeError):
                return {
                    "success": False,
                    "message": (f"Cannot set attribute '{name}' on {type(parent_obj).__name__}"),
                }
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
    value_str = value_str.strip()
    if value_str.lower() == "none":
        return None
    if value_str.lower() in ("true", "false"):
        return value_str.lower() == "true"
    try:
        return ast.literal_eval(value_str)
    except (ValueError, SyntaxError):
        pass
    if frame is not None:
        try:
            return eval(value_str, frame.f_globals, frame.f_locals)
        except Exception:
            pass
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
            pass
    return value_str


def create_variable_object(name, value):
    try:
        val_str = repr(value)
        if len(val_str) > MAX_STRING_LENGTH:
            val_str = val_str[:MAX_STRING_LENGTH] + "..."
    except Exception:
        val_str = "<Error getting value>"
    var_ref = 0
    if hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple)):
        dbg = state.debugger
        if dbg is not None:
            var_ref = dbg.next_var_ref
            dbg.next_var_ref += 1
            dbg.var_refs[var_ref] = ("object", value)
    type_name = type(value).__name__
    return {
        "name": str(name),
        "value": val_str,
        "type": type_name,
        "variablesReference": var_ref,
    }


@command_handler("evaluate")
def handle_evaluate(arguments: EvaluateArguments) -> None:
    expression = arguments.get("expression")
    frame_id = arguments.get("frameId")
    arguments.get("context", "")
    result = "<evaluation not implemented>"
    var_ref = 0
    dbg = state.debugger
    if frame_id and dbg and frame_id in dbg.frame_id_to_frame:
        frame = dbg.frame_id_to_frame[frame_id]
        try:
            value = eval(expression, frame.f_globals, frame.f_locals)
            result = repr(value)
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


@command_handler("exceptionInfo")
def handle_exception_info(arguments: ExceptionInfoArguments) -> None:
    thread_id = arguments.get("threadId")
    if thread_id is None:
        send_debug_message(
            "error",
            message="Missing required argument 'threadId'",
        )
        return
    dbg = state.debugger
    if not dbg:
        send_debug_message("error", message="Debugger not initialized")
        return
    if thread_id in dbg.current_exception_info:
        exception_info = dbg.current_exception_info[thread_id]
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


@command_handler("configurationDone")
def handle_configuration_done(_arguments: ConfigurationDoneArguments | None = None) -> None:
    """Handle configurationDone command."""
    # Currently no specific action needed for configuration done
    # The debugger is ready to receive other commands


@command_handler("terminate")
def handle_terminate(_arguments: TerminateArguments | None = None) -> None:
    """Handle terminate command."""
    state.is_terminated = True
    send_debug_message("exited", exitCode=0)


def _collect_module_sources(seen_paths: set[str]) -> list[Source]:
    """Collect sources from sys.modules."""
    sources: list[Source] = []

    for module_name, module in sys.modules.items():
        if module is None:
            continue

        # Get the module's file path
        try:
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                continue

            # Normalize the path
            module_path = Path(module_file).resolve()
            module_file = str(module_path)

            # Skip already seen paths and non-Python files
            if module_file in seen_paths:
                continue
            if not module_file.endswith((".py", ".pyw")):
                continue

            seen_paths.add(module_file)

            # Create a source object using Source's constructor
            source = Source(name=module_path.name, path=module_file)

            # Add additional information if available
            if hasattr(module, "__package__") and module.__package__:
                source["origin"] = f"module:{module.__package__}"
            else:
                source["origin"] = f"module:{module_name}"

            sources.append(source)

        except (AttributeError, TypeError, OSError):
            # Skip modules that don't have file information or cause errors
            continue

    return sources


def _collect_linecache_sources(seen_paths: set[str]) -> list[Source]:
    """Collect sources from linecache."""
    sources: list[Source] = []

    # Add sources from linecache (files that have been accessed)
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
    sources: list[Source] = []

    # Add the main program source if it exists
    if hasattr(state, "debugger") and state.debugger:
        program_path = getattr(state.debugger, "program_path", None)
        if program_path and program_path not in seen_paths:
            try:
                program_file_path = Path(program_path).resolve()
                abs_path = str(program_file_path)
                if program_file_path.exists():
                    source = Source(name=program_file_path.name, path=abs_path)
                    source["origin"] = "main"
                    sources.append(source)
            except (OSError, TypeError):
                pass

    return sources


@command_handler("loadedSources")
def handle_loaded_sources(_arguments: dict[str, Any] | None = None) -> None:
    """Handle loadedSources request to return all loaded source files."""
    # Track seen paths to avoid duplicates
    seen_paths = set[str]()

    # Collect sources from all available sources
    loaded_sources: list[Source] = []
    loaded_sources.extend(_collect_module_sources(seen_paths))
    loaded_sources.extend(_collect_linecache_sources(seen_paths))
    loaded_sources.extend(_collect_main_program_source(seen_paths))

    # Sort sources by name for consistent ordering
    loaded_sources.sort(key=lambda s: s.get("name", ""))

    # Send the response
    send_debug_message("response", success=True, body={"sources": loaded_sources})


@command_handler("modules")
def handle_modules(arguments: ModulesArguments | None = None) -> None:
    """Handle modules request to return loaded Python modules."""
    # Get all loaded modules from sys.modules
    all_modules: list[Module] = []

    for module_name, module in sys.modules.items():
        if module is None:
            continue

        try:
            # Create module information
            module_info: Module = {
                "id": module_name,
                "name": module_name,
            }

            # Add path if available
            module_file = getattr(module, "__file__", None)
            if module_file:
                module_path = Path(module_file).resolve()
                module_info["path"] = str(module_path)

                # Determine if it's user code (not in site-packages or standard library)
                path_str = str(module_path)
                is_user_code = not any(
                    part in path_str.lower()
                    for part in ["site-packages", "lib/python", "lib\\python", "Lib"]
                )
                module_info["isUserCode"] = is_user_code

            # Add version if available
            if hasattr(module, "__version__"):
                module_info["version"] = str(module.__version__)

            # Add package information
            if hasattr(module, "__package__") and module.__package__:
                # This is part of a package
                pass  # We already have the name

            all_modules.append(module_info)

        except (AttributeError, TypeError, OSError):
            # Skip modules that cause errors
            continue

    # Sort modules by name for consistent ordering
    all_modules.sort(key=lambda m: m["name"])

    # Handle paging if requested
    if arguments:
        start_module = arguments.get("startModule", 0)
        module_count = arguments.get("moduleCount", 0)

        if module_count > 0:
            # Return a slice of modules
            modules = all_modules[start_module : start_module + module_count]
        else:
            # Return all modules from start index
            modules = all_modules[start_module:]
    else:
        # Return all modules
        modules = all_modules

    # Send the response
    send_debug_message(
        "response", success=True, body={"modules": modules, "totalModules": len(all_modules)}
    )
