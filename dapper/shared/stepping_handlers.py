"""Stepping and execution-control DAP handler implementations."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from typing import Protocol

from dapper.core.stepping_controller import StepGranularity
from dapper.shared.runtime_source_registry import annotate_stack_frames_with_source_refs

# Code-flag constants for coroutine and async-generator functions (Python 3.5+).
_CO_COROUTINE: int = inspect.CO_COROUTINE
_CO_ASYNC_GENERATOR: int = inspect.CO_ASYNC_GENERATOR


def _frame_is_coroutine(frame: FrameType) -> bool:
    """Return True if *frame* belongs to a coroutine or async-generator function."""
    try:
        flags: int = frame.f_code.co_flags
        return bool(flags & (_CO_COROUTINE | _CO_ASYNC_GENERATOR))
    except AttributeError:
        return False


if TYPE_CHECKING:
    from logging import Logger
    from types import FrameType

    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.command_handler_helpers import SafeSendDebugMessageFn


class GetThreadIdentFn(Protocol):
    def __call__(self) -> int: ...


class SetDbgSteppingFlagFn(Protocol):
    def __call__(self, dbg: CommandHandlerDebuggerLike) -> None: ...


def handle_continue_impl(
    dbg: CommandHandlerDebuggerLike | None, arguments: Payload | None
) -> None:
    """Handle continue command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")

    if dbg and thread_id in dbg.thread_tracker.stopped_thread_ids:
        dbg.thread_tracker.stopped_thread_ids.remove(thread_id)
        if not dbg.thread_tracker.stopped_thread_ids:
            dbg.set_continue()


def handle_next_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle next command (step over) implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    granularity: str = arguments.get("granularity") or "line"

    _thread_is_stopped = (
        (thread_id is not None and thread_id in dbg.thread_tracker.stopped_thread_ids)
        if dbg
        else False
    )
    if dbg and (thread_id == get_thread_ident() or _thread_is_stopped):
        if _thread_is_stopped:
            dbg.thread_tracker.stopped_thread_ids.discard(thread_id)
        set_dbg_stepping_flag(dbg)
        dbg.stepping_controller.set_granularity(granularity)
        if dbg.stepping_controller.current_frame is not None:
            if _frame_is_coroutine(dbg.stepping_controller.current_frame):
                dbg.stepping_controller.set_async_step_over()
            if dbg.stepping_controller.granularity is StepGranularity.INSTRUCTION:
                # Enable per-instruction trace events and use set_step so all
                # trace events (including "opcode") fire; the debugger will stop
                # at each bytecode instruction via user_opcode.
                dbg.stepping_controller.current_frame.f_trace_opcodes = True
                dbg.set_step()
            else:
                # LINE and STATEMENT: step over to the next source line.
                dbg.set_next(dbg.stepping_controller.current_frame)


def handle_step_in_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle stepIn command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    granularity: str = arguments.get("granularity") or "line"

    _thread_is_stopped = (
        (thread_id is not None and thread_id in dbg.thread_tracker.stopped_thread_ids)
        if dbg
        else False
    )
    if dbg and (thread_id == get_thread_ident() or _thread_is_stopped):
        if _thread_is_stopped:
            dbg.thread_tracker.stopped_thread_ids.discard(thread_id)
        set_dbg_stepping_flag(dbg)
        dbg.stepping_controller.set_granularity(granularity)
        if dbg.stepping_controller.current_frame is not None and _frame_is_coroutine(
            dbg.stepping_controller.current_frame
        ):
            dbg.stepping_controller.set_async_step_over()
        if dbg.stepping_controller.granularity is StepGranularity.INSTRUCTION:
            frame = dbg.stepping_controller.current_frame
            if frame is not None:
                frame.f_trace_opcodes = True
        dbg.set_step()


def handle_step_out_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    set_dbg_stepping_flag: SetDbgSteppingFlagFn,
) -> None:
    """Handle stepOut command implementation."""
    arguments = arguments or {}
    thread_id = arguments.get("threadId")
    granularity: str = arguments.get("granularity") or "line"

    _thread_is_stopped = (
        (thread_id is not None and thread_id in dbg.thread_tracker.stopped_thread_ids)
        if dbg
        else False
    )
    if dbg and (thread_id == get_thread_ident() or _thread_is_stopped):
        if _thread_is_stopped:
            dbg.thread_tracker.stopped_thread_ids.discard(thread_id)
        set_dbg_stepping_flag(dbg)
        dbg.stepping_controller.set_granularity(granularity)
        if dbg.stepping_controller.current_frame is not None:
            dbg.set_return(dbg.stepping_controller.current_frame)


def handle_pause_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    get_thread_ident: GetThreadIdentFn,
    safe_send_debug_message: SafeSendDebugMessageFn,
    logger: Logger,
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
                    annotate_stack_frames_with_source_refs(stack_frames)
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
