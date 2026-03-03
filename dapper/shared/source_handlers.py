"""Source-related DAP handler implementations extracted from command_handlers."""

from __future__ import annotations

import linecache
import mimetypes
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dapper.protocol.structures import Source
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.debug_shared import DebugSession


def _resolve_path(raw: str) -> tuple[Path, str]:
    """Resolve *raw* to an absolute `Path` and its string form."""
    resolved = Path(raw).resolve()
    return resolved, str(resolved)


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

            module_path, module_file = _resolve_path(module_file)

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
                file_path, abs_path = _resolve_path(filename)
                if abs_path not in seen_paths and file_path.exists():
                    seen_paths.add(abs_path)
                    source = Source(name=file_path.name, path=abs_path, origin="linecache")
                    sources.append(source)
            except (OSError, TypeError):
                continue

    return sources


def _collect_main_program_source(
    seen_paths: set[str],
    state: DebugSession,
) -> list[Source]:
    """Collect the main program source if available."""
    from dapper.protocol.structures import Source  # noqa: PLC0415

    sources: list[Source] = []

    if state.debugger:
        program_path = state.debugger.program_path
        if program_path and program_path not in seen_paths:
            try:
                program_file_path, abs_path = _resolve_path(program_path)
                if program_file_path.exists():
                    sources.append(
                        Source(name=program_file_path.name, path=abs_path, origin="main")
                    )
            except (OSError, TypeError):
                pass

    return sources


def _collect_dynamic_sources(state: DebugSession) -> list[Source]:
    """Collect in-memory (dynamic) sources from the runtime source registry.

    The returned dictionaries conform to the :class:`~dapper.protocol.structures.Source`
    typed dict, so callers that perform additional static typing can treat the
    output accordingly instead of using ``dict[str, Any]`` everywhere.
    """
    # local import avoids a circular dependency during module load
    from dapper.protocol.structures import Source  # noqa: PLC0415

    return [
        Source(
            name=entry.name,
            path=entry.virtual_path,
            sourceReference=entry.ref,
            origin=entry.origin,
        )
        for entry in state.get_dynamic_sources()
    ]


def handle_loaded_sources(
    state: DebugSession,
) -> None:
    """Handle loadedSources request to return all loaded source files."""
    seen_paths = set[str]()

    loaded_sources: list[Source] = []
    loaded_sources.extend(_collect_module_sources(seen_paths))
    loaded_sources.extend(_collect_linecache_sources(seen_paths))
    loaded_sources.extend(_collect_main_program_source(seen_paths, state))

    loaded_sources.sort(key=lambda s: s.get("name", ""))

    for source_item in loaded_sources:
        path = source_item.get("path")
        if not path:
            continue
        ref_id = state.get_ref_for_path(path) or state.get_or_create_source_ref(
            path,
            source_item.get("name"),
        )
        source_item["sourceReference"] = ref_id

    # Include dynamic (in-memory) sources — these already carry sourceReference.
    loaded_sources.extend(_collect_dynamic_sources(state))

    state.safe_send(
        "response", id=state.request_id, success=True, body={"sources": loaded_sources}
    )


def handle_source(
    arguments: Payload | None,
    state: DebugSession,
) -> None:
    """Handle source request to return source content."""
    if arguments is None:
        state.safe_send(
            "response",
            id=state.request_id,
            success=False,
            message="Missing arguments for source request",
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
        state.safe_send_response(success=False, message="Could not load source content")
        return

    body: Payload = {"content": content}
    if mime_type:
        body["mimeType"] = mime_type
    state.safe_send_response(success=True, body=body)


def handle_legacy_source(
    arguments: Payload | None,
    state: DebugSession,
) -> Payload:
    """Handle source command for legacy (dbg, arguments) call shape."""
    arguments = arguments or {}
    source_reference = arguments.get("sourceReference")

    content = ""
    if source_reference is not None:
        try:
            ref_id = int(source_reference)
        except Exception:
            ref_id = None

        if ref_id and ref_id > 0:
            resolved = state.get_source_content_by_ref(ref_id)
            if resolved is not None:
                content = resolved
    else:
        path = arguments.get("path")
        if path:
            resolved = state.get_source_content_by_path(path)
            if resolved is not None:
                content = resolved

    state.safe_send("source", content=content)
    return {"success": True, "body": {"content": content}}


def handle_modules(
    arguments: Payload | None,
    state: DebugSession,
) -> None:
    """Handle modules request to return loaded Python modules."""
    all_modules: list[Payload] = []

    for module_name, module in sys.modules.items():
        if module is None:
            continue

        try:
            module_info: Payload = {
                "id": module_name,
                "name": module_name,
                "isUserCode": False,
            }

            module_file = getattr(module, "__file__", None)
            if module_file:
                _, path_str = _resolve_path(module_file)
                module_info["path"] = path_str

                is_user_code = not any(
                    part in path_str.lower()
                    for part in ["site-packages", "lib/python", "lib\\python", "Lib"]
                )
                module_info["isUserCode"] = is_user_code

            all_modules.append(module_info)

        except (AttributeError, TypeError, OSError):
            continue

    all_modules.sort(key=lambda module_info: module_info["name"])

    if arguments:
        start_module = arguments.get("startModule", 0)
        module_count = arguments.get("moduleCount", 0)

        if module_count > 0:
            modules = all_modules[start_module : start_module + module_count]
        else:
            modules = all_modules[start_module:]
    else:
        modules = all_modules

    state.safe_send(
        "response",
        id=state.request_id,
        success=True,
        body={"modules": modules, "totalModules": len(all_modules)},
    )
