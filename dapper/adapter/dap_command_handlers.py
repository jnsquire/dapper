"""
DAP command handler functions for debug launcher.

This module provides a decorator-based command registration system that
delegates to the canonical handler implementations in `launcher_handlers.py`.

Handlers that are unique to this module (loadedSources, source with enhanced
sourceReference support, modules) are kept here. All other handlers delegate
to `launcher_handlers.py` to avoid code duplication.
"""

from __future__ import annotations

import linecache
import mimetypes
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from dapper.protocol.protocol_types import LegacySourceArguments
from dapper.protocol.protocol_types import LoadedSourcesArguments
from dapper.protocol.protocol_types import Source
from dapper.shared import debug_shared as _ds
from dapper.shared import launcher_handlers as _lh
from dapper.shared.debug_shared import send_debug_message
from dapper.shared.debug_shared import state

if TYPE_CHECKING:
    from dapper.protocol.protocol_types import ConfigurationDoneArguments
    from dapper.protocol.protocol_types import ContinueArguments
    from dapper.protocol.protocol_types import EvaluateArguments
    from dapper.protocol.protocol_types import ExceptionInfoArguments
    from dapper.protocol.protocol_types import Module
    from dapper.protocol.protocol_types import ModulesArguments
    from dapper.protocol.protocol_types import NextArguments
    from dapper.protocol.protocol_types import PauseArguments
    from dapper.protocol.protocol_types import SetBreakpointsArguments
    from dapper.protocol.protocol_types import SetExceptionBreakpointsArguments
    from dapper.protocol.protocol_types import SetFunctionBreakpointsArguments
    from dapper.protocol.protocol_types import SetVariableArguments
    from dapper.protocol.protocol_types import SourceArguments
    from dapper.protocol.protocol_types import StackTraceArguments
    from dapper.protocol.protocol_types import StepInArguments
    from dapper.protocol.protocol_types import StepOutArguments
    from dapper.protocol.protocol_types import TerminateArguments
    from dapper.protocol.protocol_types import VariablesArguments


# Command mapping table - will be populated by the @command_handler decorator
COMMAND_HANDLERS: dict[str, Any] = {}

# Back-compat: expose make_variable_object at module level for tests and older callsites
make_variable_object = _ds.make_variable_object

# Re-export helpers used by tests for backward compatibility
_convert_value_with_context = _lh._convert_value_with_context  # noqa: SLF001
_set_scope_variable = _lh._set_scope_variable  # noqa: SLF001
_set_object_member = _lh._set_object_member  # noqa: SLF001


def command_handler(command_name: str):
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


# =============================================================================
# Delegating handlers - these call the canonical implementations in
# launcher_handlers.py to avoid code duplication
# =============================================================================


@command_handler("setBreakpoints")
def handle_set_breakpoints(arguments: SetBreakpointsArguments) -> None:
    """Delegate to launcher_handlers.handle_set_breakpoints."""
    dbg = state.debugger
    if dbg:
        _lh.handle_set_breakpoints(dbg, arguments)


@command_handler("setFunctionBreakpoints")
def handle_set_function_breakpoints(arguments: SetFunctionBreakpointsArguments) -> None:
    """Delegate to launcher_handlers.handle_set_function_breakpoints."""
    dbg = state.debugger
    if dbg:
        _lh.handle_set_function_breakpoints(dbg, arguments)


@command_handler("setExceptionBreakpoints")
def handle_set_exception_breakpoints(arguments: SetExceptionBreakpointsArguments) -> None:
    """Delegate to launcher_handlers.handle_set_exception_breakpoints."""
    dbg = state.debugger
    if dbg:
        _lh.handle_set_exception_breakpoints(dbg, arguments)


@command_handler("continue")
def handle_continue(arguments: ContinueArguments) -> None:
    """Delegate to launcher_handlers.handle_continue."""
    dbg = state.debugger
    if dbg:
        _lh.handle_continue(dbg, arguments)


@command_handler("next")
def handle_next(arguments: NextArguments) -> None:
    """Delegate to launcher_handlers.handle_next."""
    dbg = state.debugger
    if dbg:
        _lh.handle_next(dbg, arguments)


@command_handler("stepIn")
def handle_step_in(arguments: StepInArguments) -> None:
    """Delegate to launcher_handlers.handle_step_in."""
    dbg = state.debugger
    if dbg:
        _lh.handle_step_in(dbg, arguments)


@command_handler("stepOut")
def handle_step_out(arguments: StepOutArguments) -> None:
    """Delegate to launcher_handlers.handle_step_out."""
    dbg = state.debugger
    if dbg:
        _lh.handle_step_out(dbg, arguments)


@command_handler("pause")
def handle_pause(arguments: PauseArguments) -> None:
    """Delegate to launcher_handlers.handle_pause."""
    dbg = state.debugger
    if dbg:
        _lh.handle_pause(dbg, arguments)


@command_handler("stackTrace")
def handle_stack_trace(arguments: StackTraceArguments) -> None:
    """Delegate to launcher_handlers.handle_stack_trace."""
    dbg = state.debugger
    if dbg:
        _lh.handle_stack_trace(dbg, arguments)


@command_handler("threads")
def handle_threads(arguments: dict[str, Any] | None = None) -> None:
    """Delegate to launcher_handlers.handle_threads."""
    dbg = state.debugger
    if dbg:
        _lh.handle_threads(dbg, arguments)


@command_handler("scopes")
def handle_scopes(arguments: dict[str, Any]) -> None:
    """Delegate to launcher_handlers.handle_scopes."""
    dbg = state.debugger
    if dbg:
        _lh.handle_scopes(dbg, arguments)


@command_handler("variables")
def handle_variables(arguments: VariablesArguments) -> None:
    """Delegate to launcher_handlers.handle_variables."""
    dbg = state.debugger
    if dbg:
        _lh.handle_variables(dbg, arguments)


@command_handler("setVariable")
def handle_set_variable(arguments: SetVariableArguments) -> None:
    """Delegate to launcher_handlers.handle_set_variable."""
    dbg = state.debugger
    if dbg:
        result = _lh.handle_set_variable(dbg, arguments)
        if result:
            send_debug_message("setVariable", **result)


@command_handler("evaluate")
def handle_evaluate(arguments: EvaluateArguments) -> None:
    """Delegate to launcher_handlers.handle_evaluate."""
    dbg = state.debugger
    if dbg:
        _lh.handle_evaluate(dbg, arguments)


@command_handler("setDataBreakpoints")
def handle_set_data_breakpoints(arguments: dict[str, Any]) -> None:
    """Delegate to launcher_handlers.handle_set_data_breakpoints."""
    dbg = state.debugger
    if dbg:
        _lh.handle_set_data_breakpoints(dbg, arguments)


@command_handler("dataBreakpointInfo")
def handle_data_breakpoint_info(arguments: dict[str, Any]) -> None:
    """Delegate to launcher_handlers.handle_data_breakpoint_info."""
    dbg = state.debugger
    if dbg:
        _lh.handle_data_breakpoint_info(dbg, arguments)


@command_handler("exceptionInfo")
def handle_exception_info(arguments: ExceptionInfoArguments) -> None:
    """Handle exceptionInfo request with local error handling before delegation.
    
    This handler requires custom logic because the original implementation sends
    messages directly, while launcher_handlers returns a result dict.
    """
    thread_id = arguments.get("threadId")
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
    # Get exception info from debugger and send it
    exception_info = dbg.current_exception_info[thread_id]
    send_debug_message(
        "exceptionInfo",
        exceptionId=exception_info["exceptionId"],
        description=exception_info["description"],
        breakMode=exception_info["breakMode"],
        details=exception_info["details"],
    )


@command_handler("configurationDone")
def handle_configuration_done(_arguments: ConfigurationDoneArguments | None = None) -> None:
    """Delegate to launcher_handlers.handle_configuration_done."""
    dbg = state.debugger
    _lh.handle_configuration_done(dbg, _arguments)


@command_handler("terminate")
def handle_terminate(_arguments: TerminateArguments | None = None) -> None:
    """Delegate to launcher_handlers.handle_terminate."""
    dbg = state.debugger
    _lh.handle_terminate(dbg, _arguments)


@command_handler("initialize")
def handle_initialize(_arguments: dict[str, Any] | None = None) -> None:
    """Delegate to launcher_handlers.handle_initialize."""
    dbg = state.debugger
    result = _lh.handle_initialize(dbg, _arguments)
    if result:
        send_debug_message("response", **result)


@command_handler("restart")
def handle_restart(_arguments: dict[str, Any] | None = None) -> None:
    """Delegate to launcher_handlers.handle_restart."""
    dbg = state.debugger
    _lh.handle_restart(dbg, _arguments)


# =============================================================================
# Unique handlers - these provide enhanced functionality specific to
# dap_command_handlers that is not available in launcher_handlers
# =============================================================================


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
