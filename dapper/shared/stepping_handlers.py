"""Stepping and execution-control DAP handler implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.command_handler_helpers import SafeSendDebugMessageFn


class GetThreadIdentFn(Protocol):
    def __call__(self) -> int: ...


class SetDbgSteppingFlagFn(Protocol):
    def __call__(self, dbg: object) -> None: ...


class LoggerLike(Protocol):
    def debug(self, msg: str, *args: object, **kwargs: object) -> object: ...
    def exception(self, msg: str, *args: object, **kwargs: object) -> object: ...


def handle_continue_impl(dbg: object | None, arguments: Payload | None) -> None:
    """Handle continue command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id in dbg.thread_tracker.stopped_thread_ids:
        dbg.thread_tracker.stopped_thread_ids.remove(thread_id)
        if not dbg.thread_tracker.stopped_thread_ids:
            dbg.set_continue()


def handle_next_impl(
    dbg: object | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle next command (step over) implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == get_thread_ident():
        set_dbg_stepping_flag(dbg)
        if dbg.stepping_controller.current_frame is not None:
            dbg.set_next(dbg.stepping_controller.current_frame)


def handle_step_in_impl(
    dbg: object | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle stepIn command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == get_thread_ident():
        set_dbg_stepping_flag(dbg)
        dbg.set_step()


def handle_step_out_impl(
    dbg: object | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle stepOut command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id == get_thread_ident():
        set_dbg_stepping_flag(dbg)
        if dbg.stepping_controller.current_frame is not None:
            dbg.set_return(dbg.stepping_controller.current_frame)


def handle_pause_impl(
    dbg: object | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    safe_send_debug_message: SafeSendDebugMessageFn,
    logger: LoggerLike,
) -> None:
    """Handle pause command implementation."""
    import sys as _sys  # noqa: PLC0415

    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    try:
        thread_id = int(thread_id) if thread_id is not None else get_thread_ident()
    except Exception:
        return

    try:
        pause_fn = getattr(dbg, "pause", None)
        if callable(pause_fn):
            try:
                pause_fn(thread_id)
            except Exception:
                logger.debug("Debugger.pause(thread_id) failed", exc_info=True)
    except Exception:
        pause_fn = None

    try:
        _current_frames = getattr(_sys, "_current_frames", dict)
        frame = _current_frames().get(thread_id)
    except Exception:
        frame = None

    try:
        if dbg:
            try:
                dbg.thread_tracker.stopped_thread_ids.add(thread_id)
            except Exception:
                pass

            if frame is not None:
                try:
                    stack_frames = dbg.thread_tracker.build_stack_frames(frame)
                    dbg.thread_tracker.frames_by_thread[thread_id] = stack_frames
                    dbg.stepping_controller.current_frame = frame
                except Exception:
                    logger.debug("Failed to build/store stack frames for pause", exc_info=True)

            safe_send_debug_message(
                "stopped",
                threadId=thread_id,
                reason="pause",
                allThreadsStopped=True,
            )
    except Exception:
        logger.exception("Error handling pause command")
