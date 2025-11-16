"""
DAP command handler functions for debug launcher.
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

from dapper import debug_shared as _ds
from dapper.debug_shared import VAR_REF_TUPLE_SIZE
from dapper.debug_shared import send_debug_message
from dapper.debug_shared import state
from dapper.protocol_types import LegacySourceArguments
from dapper.protocol_types import LoadedSourcesArguments
from dapper.protocol_types import Source

# small constant to make argcount checks clearer / lint-friendly
_SIMPLE_MAKE_VAR_ARGCOUNT = 2


if TYPE_CHECKING:
    from dapper.debugger_protocol import ExceptionInfo
    from dapper.debugger_protocol import Variable
    from dapper.protocol_types import ConfigurationDoneArguments
    from dapper.protocol_types import ContinueArguments
    from dapper.protocol_types import EvaluateArguments
    from dapper.protocol_types import ExceptionInfoArguments
    from dapper.protocol_types import LegacySourceArguments
    from dapper.protocol_types import Module
    from dapper.protocol_types import ModulesArguments
    from dapper.protocol_types import NextArguments
    from dapper.protocol_types import PauseArguments
    from dapper.protocol_types import SetBreakpointsArguments
    from dapper.protocol_types import SetExceptionBreakpointsArguments
    from dapper.protocol_types import SetFunctionBreakpointsArguments
    from dapper.protocol_types import SetVariableArguments
    from dapper.protocol_types import SourceArguments
    from dapper.protocol_types import StackTraceArguments
    from dapper.protocol_types import StepInArguments
    from dapper.protocol_types import StepOutArguments
    from dapper.protocol_types import TerminateArguments
    from dapper.protocol_types import VariablesArguments


# Command mapping table - will be populated by the @command_handler decorator
COMMAND_HANDLERS = {}

# Back-compat: expose make_variable_object at module level for tests and older callsites
make_variable_object = _ds.make_variable_object


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
    # 'breakpoints' is expected to be a list of dict-like entries with
    # optional fields such as line, condition, hitCondition and logMessage.
    bps = arguments.get("breakpoints", [])
    path = source.get("path")
    if path and state.debugger:
        # Clear all breakpoints for this file and its metadata
        try:
            state.debugger.clear_breaks_for_file(path)  # type: ignore[attr-defined]
        except Exception:
            # Fallbacks for older implementations
            # 1) Older debuggers may expose clear_break(path) without lineno
            try:
                state.debugger.clear_break(path)  # type: ignore[misc]
            except Exception:
                # 2) As a last resort, clear only stored metadata
                try:
                    state.debugger.clear_break_meta_for_file(path)
                except Exception:
                    pass

        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")
            if line is not None:
                state.debugger.set_break(path, line, cond=condition)
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
        state.debugger.clear_all_function_breakpoints()

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
        variables = []
        # frame_info can have multiple shapes; handle scope-backed refs here
        if (
            isinstance(frame_info, tuple)
            and len(frame_info) == VAR_REF_TUPLE_SIZE
            and isinstance(frame_info[0], int)
        ):
            frame_id, scope = cast("tuple", frame_info)
            frame = dbg.frame_id_to_frame.get(cast("int", frame_id))
            if frame and scope == "locals":
                for name, value in frame.f_locals.items():
                    fn = getattr(dbg, "make_variable_object", None)
                    if callable(fn):
                        try:
                            # accept simple or extended signature
                            var_obj = (
                                fn(name, value)
                                if fn.__code__.co_argcount <= _SIMPLE_MAKE_VAR_ARGCOUNT
                                else fn(name, value, frame)
                            )
                            if isinstance(var_obj, dict):
                                variables.append(cast("Variable", var_obj))
                                continue
                        except Exception:
                            pass
                    # fallback to shared helper
                    variables.append(_ds.make_variable_object(name, value, dbg, frame))
            elif frame and scope == "globals":
                for name, value in frame.f_globals.items():
                    fn = getattr(dbg, "make_variable_object", None)
                    if callable(fn):
                        try:
                            var_obj = (
                                fn(name, value)
                                if fn.__code__.co_argcount <= _SIMPLE_MAKE_VAR_ARGCOUNT
                                else fn(name, value, frame)
                            )
                            if isinstance(var_obj, dict):
                                variables.append(cast("Variable", var_obj))
                                continue
                        except Exception:
                            pass
                    variables.append(_ds.make_variable_object(name, value, dbg, frame))
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
        fn = getattr(state.debugger, "make_variable_object", None)
        if callable(fn):
            try:
                var_obj = (
                    fn(name, new_value)
                    if fn.__code__.co_argcount <= _SIMPLE_MAKE_VAR_ARGCOUNT
                    else fn(name, new_value, frame)
                )
            except Exception:
                var_obj = None
        else:
            var_obj = None
        if not var_obj:
            var_obj = _ds.make_variable_object(name, new_value, state.debugger, frame)
        # var_obj can be various types; ensure mapping access is safe for the body
        vobj = cast("dict[str, Any]", var_obj)
        return {
            "success": True,
            "body": {
                "value": vobj["value"],
                "type": vobj["type"],
                "variablesReference": vobj["variablesReference"],
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
                parent_obj[index] = new_value
            except (ValueError, IndexError):
                return {
                    "success": False,
                    "message": f"Invalid or out-of-range list index: {name}",
                }

        elif isinstance(parent_obj, tuple):
            return {
                "success": False,
                "message": "Cannot modify tuple - tuples are immutable",
            }

        else:
            # Try to set attribute on arbitrary objects; handle failures uniformly.
            try:
                setattr(parent_obj, name, new_value)
            except (AttributeError, TypeError):
                return {
                    "success": False,
                    "message": f"Cannot set attribute '{name}' on {type(parent_obj).__name__}",
                }

        dbg = state.debugger
        fn = getattr(dbg, "make_variable_object", None) if dbg is not None else None
        try:
            if callable(fn):
                var_obj = fn(name, new_value)
            else:
                var_obj = _ds.make_variable_object(name, new_value, dbg)
        except Exception:
            # Fall back to shared helper on any error from custom make_variable_object
            var_obj = _ds.make_variable_object(name, new_value, dbg)

        vobj = cast("dict[str, Any]", var_obj)
        return {
            "success": True,
            "body": {
                "value": vobj["value"],
                "type": vobj["type"],
                "variablesReference": vobj["variablesReference"],
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


# The canonical helper for creating Variable-shaped dicts is provided in
# dapper.debug_shared.make_variable_object. Callers should prefer using the
# debugger instance's `make_variable_object` when available (it may accept an
# optional frame argument); otherwise import and call the shared helper.


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
        exception_info: ExceptionInfo = dbg.current_exception_info[thread_id]
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

            # Build a minimal Source-shaped dict for this module and cast
            origin = getattr(module, "__package__", module_name)
            source_obj = Source(name=module_path.name, path=module_file, origin=f"module:{origin}")

            sources.append(source_obj)

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


@command_handler("loadedSources")
def handle_loaded_sources(_arguments: LoadedSourcesArguments | None = None) -> None:
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

    # Assign sourceReference ids and populate state mapping
    # Reuse existing ids for paths already known, otherwise allocate new ids
    # via the State API
    for s in loaded_sources:
        p = s.get("path")
        if not p:
            continue
        # Use State API to get or create a session-scoped id
        ref_id = state.get_ref_for_path(p) or state.get_or_create_source_ref(p, s.get("name"))
        s["sourceReference"] = ref_id

    # Send the response
    send_debug_message("response", success=True, body={"sources": loaded_sources})


@command_handler("source")
def handle_source(
    arguments: SourceArguments | LegacySourceArguments | dict[str, Any] | None = None,
) -> None:
    """Handle 'source' request to return source content by path or sourceReference.

    According to the Debug Adapter Protocol specification, this handles two formats:

    1. Preferred format (SourceArguments):
       {
           "source": {
               "sourceReference": 123  // or "path": "/path/to/source"
           }
       }

    2. Legacy format (LegacySourceArguments, for backward compatibility):
       {
           "sourceReference": 123
       }

    Args:
        arguments: Either a SourceArguments object (preferred) or LegacySourceArguments
                  object (for backward compatibility), or a raw dict matching one of
                  these formats.
    """
    if arguments is None:
        send_debug_message(
            "response", success=False, message="Missing arguments for source request"
        )
        return

    # Extract source reference and path based on the format
    # 1. Check for the preferred format with nested 'source' key (SourceArguments)
    if (
        isinstance(arguments, dict)
        and "source" in arguments
        and isinstance(arguments["source"], dict)
    ):
        source = arguments["source"]
        source_reference = source.get("sourceReference")
        path = source.get("path")
    else:
        # 2. Handle legacy format with direct keys (LegacySourceArguments)
        source = arguments
        source_reference = source.get("sourceReference")
        path = source.get("path")
    # Resolve content (by sourceReference preferred, else by path)
    content = None
    mime_type: str | None = None

    if source_reference and isinstance(source_reference, int) and source_reference > 0:
        # Prefer resolving by reference; meta may provide the canonical path
        meta = state.get_source_meta(source_reference)
        if meta:
            path = meta.get("path") or path
        content = state.get_source_content_by_ref(source_reference)
    elif path:
        content = state.get_source_content_by_path(path)

    # If we found content and have a path, try to determine a conservative mimeType.
    if content is not None and path and "\x00" not in content:
        # If it contains a NUL byte we consider it binary and skip mimeType detection
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
