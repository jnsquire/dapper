"""Stack/thread/scope DAP handler implementations."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import TYPE_CHECKING
from typing import Protocol

from dapper.shared.runtime_source_registry import annotate_stack_frames_with_source_refs

if TYPE_CHECKING:
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.debug_shared import DebugSession


class GetThreadIdentFn(Protocol):
    def __call__(self) -> int: ...


def handle_stack_trace_impl(  # noqa: PLR0912
    session: DebugSession,
    arguments: Payload | None,
    *,
    get_thread_ident: GetThreadIdentFn,
) -> Payload:
    """Handle stackTrace command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels")

    stack_frames: list[Payload] = []
    dbg = session.debugger

    frames = None
    if dbg and isinstance(thread_id, int) and thread_id in dbg.thread_tracker.frames_by_thread:
        raw_frames = dbg.thread_tracker.frames_by_thread[thread_id]
        for entry in raw_frames:
            if isinstance(entry, dict):
                stack_frames.append(entry)
            elif hasattr(entry, "to_dict"):
                stack_frames.append(entry.to_dict())
            else:
                # (frame, lineno) tuple fallback
                frame, lineno = entry
                name = frame.f_code.co_name
                source_path = frame.f_code.co_filename
                stack_frames.append(
                    {
                        "id": len(stack_frames),
                        "name": name,
                        "source": {"name": Path(source_path).name, "path": source_path},
                        "line": lineno,
                        "column": 0,
                    }
                )
    else:
        if dbg:
            stack = dbg.stack
            if stack is not None and thread_id == get_thread_ident():
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

                stack_frames.append(
                    {
                        "id": i,
                        "name": name,
                        "source": {"name": Path(source_path).name, "path": source_path},
                        "line": lineno,
                        "column": 0,
                    }
                )

        # Annotate any synthetic-filename frames with sourceReference so
        # DAP clients can fetch the in-memory source via the source request.
        annotate_stack_frames_with_source_refs(stack_frames)

    session.safe_send(
        "stackTrace",
        threadId=thread_id,
        stackFrames=stack_frames,
        totalFrames=len(stack_frames),
    )

    return {"success": True, "body": {"stackFrames": stack_frames}}


def handle_threads_impl(
    session: DebugSession,
    _arguments: Payload | None,
) -> Payload:
    """Handle threads command implementation."""
    threads = []
    dbg = session.debugger
    if dbg and dbg.thread_tracker.threads:
        # Build a live name map from threading.enumerate() so that names
        # changed after registration (e.g. thread.name = 'worker') are
        # reflected immediately rather than returning the stale stored value.
        live_names: dict[int, str] = {
            t.ident: t.name for t in threading.enumerate() if t.ident is not None
        }
        for tid, thread_obj in dbg.thread_tracker.threads.items():
            stored_name = (
                thread_obj
                if isinstance(thread_obj, str)
                else getattr(thread_obj, "name", f"Thread-{tid}")
            )
            name = live_names.get(tid, stored_name)
            threads.append({"id": tid, "name": name})

    session.safe_send("threads", threads=threads)
    return {"success": True, "body": {"threads": threads}}


def handle_scopes_impl(
    session: DebugSession,
    arguments: Payload | None,
    *,
    var_ref_tuple_size: int,  # noqa: ARG001
) -> Payload:
    """Handle scopes command implementation."""
    arguments = arguments or {}
    frame_id = arguments.get("frameId")

    scopes = []
    dbg = session.debugger
    if frame_id is not None:
        frame = None
        if dbg:
            frame = dbg.thread_tracker.frame_id_to_frame.get(frame_id)
        if not frame and dbg and dbg.stack:
            try:
                stack = dbg.stack
                if stack is not None and frame_id is not None and frame_id < len(stack):
                    frame, _ = stack[frame_id]
                else:
                    frame = None
            except (AttributeError, IndexError, KeyError, TypeError):
                frame = None
        if frame is not None:
            # Allocate proper variable references through var_manager
            # so that the variables handler can resolve them.
            assert dbg is not None  # narrow type for the checker
            # var_manager may not be statically typed as having allocate_scope_ref
            locals_ref = dbg.var_manager.allocate_scope_ref(frame_id, "locals")  # type: ignore[attr-defined]
            globals_ref = dbg.var_manager.allocate_scope_ref(frame_id, "globals")  # type: ignore[attr-defined]
            scopes = [
                {
                    "name": "Locals",
                    "variablesReference": locals_ref,
                    "expensive": False,
                },
                {
                    "name": "Globals",
                    "variablesReference": globals_ref,
                    "expensive": True,
                },
            ]

    session.safe_send("scopes", scopes=scopes)
    return {"success": True, "body": {"scopes": scopes}}
