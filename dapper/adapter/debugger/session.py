from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class _PyDebuggerSessionFacade:
    """Encapsulates mutable debugger session state and pending command lifecycle."""

    def __init__(self, lock: threading.RLock, loop: asyncio.AbstractEventLoop):
        self._lock = lock
        self._loop = loop
        self._threads: dict[int, Any] = {}
        self._var_refs: dict[int, object] = {}
        self._breakpoints: dict[str, list[dict[str, Any]]] = {}
        self._function_breakpoints: list[dict[str, Any]] = []
        self._current_stack_frames: dict[int, list[Any]] = {}
        self._thread_exit_events: dict[int, object] = {}
        self._data_watches: dict[str, dict[str, Any]] = {}
        self._frame_watches: dict[int, list[str]] = {}
        self._next_command_id = 1
        self._pending_commands: dict[int, asyncio.Future[dict[str, Any]]] = {}

    @property
    def threads(self) -> dict[int, Any]:
        return self._threads

    @threads.setter
    def threads(self, value: dict[int, Any]) -> None:
        self._threads = value

    @property
    def var_refs(self) -> dict[int, object]:
        return self._var_refs

    @var_refs.setter
    def var_refs(self, value: dict[int, object]) -> None:
        self._var_refs = value

    @property
    def breakpoints(self) -> dict[str, list[dict[str, Any]]]:
        return self._breakpoints

    @breakpoints.setter
    def breakpoints(self, value: dict[str, list[dict[str, Any]]]) -> None:
        self._breakpoints = value

    @property
    def current_stack_frames(self) -> dict[int, list[Any]]:
        return self._current_stack_frames

    @current_stack_frames.setter
    def current_stack_frames(self, value: dict[int, list[Any]]) -> None:
        self._current_stack_frames = value

    @property
    def function_breakpoints(self) -> list[dict[str, Any]]:
        return self._function_breakpoints

    @function_breakpoints.setter
    def function_breakpoints(self, value: list[dict[str, Any]]) -> None:
        self._function_breakpoints = value

    @property
    def thread_exit_events(self) -> dict[int, object]:
        return self._thread_exit_events

    @thread_exit_events.setter
    def thread_exit_events(self, value: dict[int, object]) -> None:
        self._thread_exit_events = value

    @property
    def data_watches(self) -> dict[str, dict[str, Any]]:
        return self._data_watches

    @data_watches.setter
    def data_watches(self, value: dict[str, dict[str, Any]]) -> None:
        self._data_watches = value

    @property
    def frame_watches(self) -> dict[int, list[str]]:
        return self._frame_watches

    @frame_watches.setter
    def frame_watches(self, value: dict[int, list[str]]) -> None:
        self._frame_watches = value

    @property
    def pending_commands(self) -> dict[int, asyncio.Future[dict[str, Any]]]:
        return self._pending_commands

    @pending_commands.setter
    def pending_commands(self, value: dict[int, asyncio.Future[dict[str, Any]]]) -> None:
        self._pending_commands = value

    @property
    def next_command_id(self) -> int:
        return self._next_command_id

    @next_command_id.setter
    def next_command_id(self, value: int) -> None:
        self._next_command_id = value

    def allocate_command_id(self) -> int:
        with self._lock:
            cmd_id = self._next_command_id
            self._next_command_id += 1
        return cmd_id

    def get_thread(self, thread_id: int) -> Any | None:
        with self._lock:
            return self._threads.get(thread_id)

    def iter_threads(self) -> list[tuple[int, Any]]:
        with self._lock:
            return list(self._threads.items())

    def set_thread(self, thread_id: int, thread: Any) -> None:
        with self._lock:
            self._threads[thread_id] = thread

    def remove_thread(self, thread_id: int) -> None:
        with self._lock:
            self._threads.pop(thread_id, None)

    def cache_stack_frames(self, thread_id: int, frames: list[Any]) -> None:
        with self._lock:
            self._current_stack_frames[thread_id] = frames

    def get_cached_stack_frames(self, thread_id: int) -> list[Any] | None:
        with self._lock:
            return self._current_stack_frames.get(thread_id)

    def cache_var_ref(self, var_ref: int, value: object) -> None:
        with self._lock:
            self._var_refs[var_ref] = value

    def get_var_ref(self, var_ref: int) -> object | None:
        with self._lock:
            return self._var_refs.get(var_ref)

    def has_var_ref(self, var_ref: int) -> bool:
        with self._lock:
            return var_ref in self._var_refs

    def set_breakpoints_for_path(self, path: str, breakpoints: list[dict[str, Any]]) -> None:
        with self._lock:
            self._breakpoints[path] = breakpoints

    def clear_data_watch_containers(self) -> None:
        with self._lock:
            self._data_watches.clear()
            self._frame_watches.clear()

    def set_data_watch(self, data_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            self._data_watches[data_id] = meta

    def add_frame_watch(self, frame_id: int, data_id: str) -> None:
        with self._lock:
            self._frame_watches.setdefault(frame_id, []).append(data_id)

    def clear_runtime_state(self) -> None:
        with self._lock:
            self._var_refs.clear()
            self._threads.clear()
            self._breakpoints.clear()
            self._function_breakpoints.clear()
            self._current_stack_frames.clear()
            self._thread_exit_events.clear()
            self._data_watches.clear()
            self._frame_watches.clear()

    def has_pending_command(self, command_id: int) -> bool:
        with self._lock:
            return command_id in self._pending_commands

    def pop_pending_command(self, command_id: int) -> asyncio.Future[dict[str, Any]] | None:
        with self._lock:
            return self._pending_commands.pop(command_id, None)

    def resolve_pending_response(
        self, future: asyncio.Future[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        if future.done():
            return

        def _set_result() -> None:
            if not future.done():
                future.set_result(data)

        future_loop = future.get_loop()

        try:
            if asyncio.get_running_loop() is future_loop:
                _set_result()
                return
        except RuntimeError:
            pass

        try:
            future_loop.call_soon_threadsafe(_set_result)
        except Exception:
            logger.debug("failed to schedule resolution on debugger loop")

    def fail_pending_commands(self, error: BaseException) -> None:
        with self._lock:
            pending = dict(self._pending_commands)
            self._pending_commands.clear()

        for command_id, future in pending.items():
            if future.done():
                continue

            future_loop = future.get_loop()

            def _set_exception(f: asyncio.Future[dict[str, Any]] = future) -> None:
                if not f.done():
                    f.set_exception(error)

            try:
                if asyncio.get_running_loop() is future_loop:
                    _set_exception()
                else:
                    completion = threading.Event()

                    def _set_exception_with_signal(
                        f: asyncio.Future[dict[str, Any]] = future,
                        done: threading.Event = completion,
                    ) -> None:
                        try:
                            if not f.done():
                                f.set_exception(error)
                        finally:
                            done.set()

                    future_loop.call_soon_threadsafe(_set_exception_with_signal)
                    completion.wait(timeout=0.2)
            except Exception:
                try:
                    completion = threading.Event()

                    def _set_exception_with_signal(
                        f: asyncio.Future[dict[str, Any]] = future,
                        done: threading.Event = completion,
                    ) -> None:
                        try:
                            if not f.done():
                                f.set_exception(error)
                        finally:
                            done.set()

                    future_loop.call_soon_threadsafe(_set_exception_with_signal)
                    completion.wait(timeout=0.2)
                except Exception:
                    logger.debug("failed to fail pending future %s", command_id)
