"""Stack/thread/scope DAP handler implementations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.command_handler_helpers import SafeSendDebugMessageFn


class GetThreadIdentFn(Protocol):
    def __call__(self) -> int: ...


def handle_stack_trace_impl(
    dbg: object | None,
    arguments: Payload | None,
    *,
    get_thread_ident: GetThreadIdentFn,
    safe_send_debug_message: SafeSendDebugMessageFn,
) -> Payload:
    """Handle stackTrace command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    start_frame = arguments.get("startFrame", 0)
    levels = arguments.get("levels")

    stack_frames: list[Payload] = []

    frames = None
    if (
        dbg
        and hasattr(dbg, "thread_tracker")
        and isinstance(thread_id, int)
        and thread_id in getattr(dbg.thread_tracker, "frames_by_thread", {})
    ):
        frames = dbg.thread_tracker.frames_by_thread[thread_id]
    else:
        if dbg:
            stack = getattr(dbg, "stack", None)
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

    safe_send_debug_message(
        "stackTrace",
        threadId=thread_id,
        stackFrames=stack_frames,
        totalFrames=len(stack_frames),
    )

    return {"success": True, "body": {"stackFrames": stack_frames}}


def handle_threads_impl(
    dbg: object | None,
    _arguments: Payload | None,
    safe_send_debug_message: SafeSendDebugMessageFn,
) -> Payload:
    """Handle threads command implementation."""
    threads = []
    if dbg and getattr(dbg.thread_tracker, "threads", None):
        for tid, thread_obj in dbg.thread_tracker.threads.items():
            name = (
                thread_obj
                if isinstance(thread_obj, str)
                else getattr(thread_obj, "name", f"Thread-{tid}")
            )
            threads.append({"id": tid, "name": name})

    safe_send_debug_message("threads", threads=threads)
    return {"success": True, "body": {"threads": threads}}


def handle_scopes_impl(
    dbg: object | None,
    arguments: Payload | None,
    *,
    safe_send_debug_message: SafeSendDebugMessageFn,
    var_ref_tuple_size: int,
) -> Payload:
    """Handle scopes command implementation."""
    arguments = arguments or {}
    frame_id = arguments.get("frameId")

    scopes = []
    if frame_id is not None:
        frame = None
        if dbg and getattr(dbg.thread_tracker, "frame_id_to_frame", None):
            frame = dbg.thread_tracker.frame_id_to_frame.get(frame_id)
        elif dbg and getattr(dbg, "stack", None):
            try:
                stack = getattr(dbg, "stack", None)
                if stack is not None and frame_id is not None and frame_id < len(stack):
                    frame, _ = stack[frame_id]
                else:
                    frame = None
            except (AttributeError, IndexError, KeyError, TypeError):
                frame = None
        if frame is not None:
            scopes = [
                {
                    "name": "Locals",
                    "variablesReference": frame_id * var_ref_tuple_size,
                    "expensive": False,
                },
                {
                    "name": "Globals",
                    "variablesReference": frame_id * var_ref_tuple_size + 1,
                    "expensive": True,
                },
            ]

    safe_send_debug_message("scopes", scopes=scopes)
    return {"success": True, "body": {"scopes": scopes}}
