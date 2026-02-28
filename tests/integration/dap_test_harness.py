"""Reusable test harnesses for DAP integration tests.

Provides two harness levels:

1. **LauncherHarness** — wires a ``DebugSession`` to a local TCP socket pair
   with binary IPC framing.  No real debugger; good for testing command
   dispatch and protocol-level invariants (id echo, ordering, etc.).

2. **DebuggerHarness** — extends ``LauncherHarness`` with a *real*
   ``DebuggerBDB`` instance so that breakpoints, stepping, variable
   inspection, and program execution actually work end-to-end.
"""

from __future__ import annotations

import bdb
import json
import socket
import threading
import time
from typing import Any

import pytest

from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import unpack_header
from dapper.launcher import debug_launcher
from dapper.shared import debug_shared

# Binary IPC constants matching the launcher's protocol
KIND_EVENT = 1
KIND_COMMAND = 2


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------


def make_command_frame(
    command: str,
    arguments: dict[str, Any] | None = None,
    *,
    request_id: int | None = None,
) -> bytes:
    """Build a binary IPC frame for a DAP command."""
    payload: dict[str, Any] = {"command": command, "arguments": arguments or {}}
    if request_id is not None:
        payload["id"] = request_id
    return pack_frame(KIND_COMMAND, json.dumps(payload).encode("utf-8"))


def drain_messages(sock: socket.socket, *, timeout: float = 2.0) -> list[dict[str, Any]]:
    """Read all pending messages until the socket is quiet for *timeout*."""
    msgs: list[dict[str, Any]] = []
    sock.settimeout(0.2)
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            if not buf:
                continue
        while len(buf) >= HEADER_SIZE:
            try:
                _kind, length = unpack_header(buf[:HEADER_SIZE])
            except ValueError:
                buf = b""
                break
            if len(buf) < HEADER_SIZE + length:
                break
            payload = buf[HEADER_SIZE : HEADER_SIZE + length]
            buf = buf[HEADER_SIZE + length :]
            msgs.append(json.loads(payload.decode("utf-8")))
    return msgs


def read_one_message(sock: socket.socket, *, timeout: float = 5.0) -> dict[str, Any]:
    """Read exactly one binary IPC message from *sock*."""
    sock.settimeout(timeout)
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("Socket closed before a complete message was received")
        buf += chunk
        if len(buf) >= HEADER_SIZE:
            _kind, length = unpack_header(buf[:HEADER_SIZE])
            if len(buf) >= HEADER_SIZE + length:
                payload = buf[HEADER_SIZE : HEADER_SIZE + length]
                return json.loads(payload.decode("utf-8"))


def wait_for_event(
    sock: socket.socket,
    event_name: str,
    *,
    timeout: float = 10.0,
    extra_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Block until a message with ``event == event_name`` arrives.

    *extra_filter* is an optional dict of key/value pairs that must also match.
    Returns the first matching message.  Times out with ``AssertionError``.
    """
    deadline = time.monotonic() + timeout
    sock.settimeout(0.2)
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            continue

        while len(buf) >= HEADER_SIZE:
            try:
                _kind, length = unpack_header(buf[:HEADER_SIZE])
            except ValueError:
                buf = b""
                break
            if len(buf) < HEADER_SIZE + length:
                break
            payload_bytes = buf[HEADER_SIZE : HEADER_SIZE + length]
            buf = buf[HEADER_SIZE + length :]
            msg = json.loads(payload_bytes.decode("utf-8"))
            if msg.get("event") == event_name and (
                extra_filter is None or all(msg.get(k) == v for k, v in extra_filter.items())
            ):
                return msg
    msg = f"Timed out waiting for event={event_name!r} (filter={extra_filter})"
    raise AssertionError(msg)


def collect_until(
    sock: socket.socket,
    predicate,
    *,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Read messages until *predicate(msgs)* returns ``True``."""
    msgs: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    sock.settimeout(0.2)
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            pass  # check predicate after timeout too

        while len(buf) >= HEADER_SIZE:
            try:
                _kind, length = unpack_header(buf[:HEADER_SIZE])
            except ValueError:
                buf = b""
                break
            if len(buf) < HEADER_SIZE + length:
                break
            payload_bytes = buf[HEADER_SIZE : HEADER_SIZE + length]
            buf = buf[HEADER_SIZE + length :]
            msgs.append(json.loads(payload_bytes.decode("utf-8")))

        if predicate(msgs):
            return msgs
    return msgs  # return what we have even on timeout


# ---------------------------------------------------------------------------
# Message query helpers
# ---------------------------------------------------------------------------


def responses(
    msgs: list[dict[str, Any]], *, request_id: int | None = None
) -> list[dict[str, Any]]:
    """Filter for response messages, optionally matching a request *request_id*."""
    result = [m for m in msgs if m.get("event") == "response"]
    if request_id is not None:
        result = [m for m in result if m.get("id") == request_id]
    return result


def events(msgs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Filter for event messages matching *name*."""
    return [m for m in msgs if m.get("event") == name]


# ---------------------------------------------------------------------------
# LauncherHarness
# ---------------------------------------------------------------------------


class LauncherHarness:
    """TCP socket pair + ``DebugSession`` with binary IPC, no real debugger."""

    def __init__(self) -> None:
        self.session = debug_shared.DebugSession()
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", 0))
        self._server_sock.listen(1)
        self.host, self.port = self._server_sock.getsockname()
        self.client_sock: socket.socket | None = None
        self._cmd_thread: threading.Thread | None = None
        self._next_id = 1

    # -- lifecycle --

    def connect_session(self) -> None:
        """Wire the session's IPC transport to a TCP socket."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        self.session.ipc_sock = sock
        self.session.ipc_rfile = sock.makefile("rb", buffering=0)
        self.session.ipc_wfile = sock.makefile("wb", buffering=0)
        self.session.ipc_enabled = True
        self.session.ipc_binary = True
        self.client_sock, _ = self._server_sock.accept()

    def start_command_listener(self) -> None:
        self._cmd_thread = debug_launcher.start_command_listener(session=self.session)

    def close(self) -> None:
        self.session.is_terminated = True
        # Unblock the debugger thread if it's waiting for commands
        self.session.signal_resume()
        # Shut down sockets so the listener thread gets an immediate error
        # instead of blocking in read_exact until the OS notices.
        for s in (self.client_sock, self.session.ipc_sock):
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        # Wait for the listener thread to exit
        if self._cmd_thread is not None:
            self._cmd_thread.join(timeout=2.0)
        for s in (self.client_sock, self.session.ipc_sock, self._server_sock):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        # Clear BDB class-level breakpoint state so it doesn't leak between tests
        bdb.Breakpoint.clearBreakpoints()

    # -- send helpers --

    def send(self, frame: bytes) -> None:
        assert self.client_sock is not None
        self.client_sock.sendall(frame)

    def send_command(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        request_id: int | None = None,
    ) -> int:
        """Build and send a command frame, returning the request id used."""
        if request_id is None:
            request_id = self._next_id
            self._next_id += 1
        self.send(make_command_frame(command, arguments, request_id=request_id))
        return request_id

    # -- receive helpers --

    def read_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert self.client_sock is not None
        return drain_messages(self.client_sock, **kwargs)

    def wait_for_event(self, event_name: str, **kwargs: Any) -> dict[str, Any]:
        assert self.client_sock is not None
        return wait_for_event(self.client_sock, event_name, **kwargs)

    def collect_until(self, predicate, **kwargs: Any) -> list[dict[str, Any]]:
        assert self.client_sock is not None
        return collect_until(self.client_sock, predicate, **kwargs)

    def send_and_collect_response(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Send a command and drain messages until its response arrives."""
        rid = self.send_command(command, arguments)
        msgs = self.collect_until(
            lambda msgs: any(m.get("event") == "response" and m.get("id") == rid for m in msgs),
            timeout=timeout,
        )
        return rid, msgs

    # -- DAP handshake shortcut --

    def do_handshake(
        self,
        breakpoints: dict[str, list[int]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run the full initialize → setBreakpoints → configurationDone sequence.

        *breakpoints* maps file paths to lists of line numbers.
        Returns all collected messages.
        """
        all_msgs: list[dict[str, Any]] = []

        # initialize
        _rid, msgs = self.send_and_collect_response("initialize")
        all_msgs.extend(msgs)
        # Also drain the initialized event that follows
        all_msgs.extend(self.read_messages(timeout=1))

        # setBreakpoints (per file)
        if breakpoints:
            for path, lines in breakpoints.items():
                bp_args = {
                    "source": {"path": path},
                    "breakpoints": [{"line": ln} for ln in lines],
                }
                _rid, msgs = self.send_and_collect_response("setBreakpoints", bp_args)
                all_msgs.extend(msgs)

        # configurationDone
        _rid, msgs = self.send_and_collect_response("configurationDone")
        all_msgs.extend(msgs)

        return all_msgs


# ---------------------------------------------------------------------------
# DebuggerHarness — adds a *real* DebuggerBDB
# ---------------------------------------------------------------------------


class DebuggerHarness(LauncherHarness):
    """``LauncherHarness`` plus a real ``DebuggerBDB`` that can execute code,
    hit breakpoints, emit ``stopped`` events, and respond to inspection
    commands from the test acting as the DAP client.

    The debugger runs the target script in a background thread so the test
    thread can keep sending/receiving DAP messages.
    """

    def __init__(self, *, stop_on_entry: bool = False, just_my_code: bool = True) -> None:
        super().__init__()
        self._stop_on_entry = stop_on_entry
        self._just_my_code = just_my_code
        self._runner_thread: threading.Thread | None = None
        self._runner_error: Exception | None = None
        self._runner_done = threading.Event()

    def configure_debugger(self) -> None:
        """Create and store a real ``DebuggerBDB`` on the session."""
        debug_launcher.configure_debugger(
            self._stop_on_entry,
            session=self.session,
            just_my_code=self._just_my_code,
        )

    def run_script(self, script_path: str, *, program_args: list[str] | None = None) -> None:
        """Launch *script_path* under the debugger in a background thread.

        The test must have already called :meth:`do_handshake` (or at least
        sent ``configurationDone``) before calling this, since
        ``run_with_debugger`` blocks inside ``dbg.run()`` until the program
        finishes (or until a ``stopped`` event suspends it and commands
        resume it).
        """
        args = program_args or []

        def _run() -> None:
            try:
                debug_launcher.run_with_debugger(script_path, args, session=self.session)
            except SystemExit:
                pass  # normal exit from exec'd scripts
            except Exception as exc:
                self._runner_error = exc
            finally:
                self._runner_done.set()

        self._runner_thread = threading.Thread(target=_run, daemon=True, name="dbg-runner")
        self._runner_thread.start()

    def run_script_after_handshake(
        self,
        script_path: str,
        breakpoints: dict[str, list[int]] | None = None,
        *,
        program_args: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience: handshake + launch in one call.

        Returns the handshake messages.  After this returns the debugger
        thread is running and the test can :meth:`wait_for_event` on
        ``"stopped"`` etc.
        """
        self.configure_debugger()
        msgs = self.do_handshake(breakpoints=breakpoints)
        self.run_script(script_path, program_args=program_args)
        return msgs

    def wait_for_runner(self, timeout: float = 10.0) -> None:
        """Wait for the debugger runner thread to finish."""
        assert self._runner_done.wait(timeout=timeout), "Runner thread did not finish in time"
        if self._runner_error:
            raise self._runner_error

    def send_continue(self, thread_id: int = 0) -> int:
        """Send a ``continue`` command.  Returns the request id."""
        return self.send_command("continue", {"threadId": thread_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def harness():
    """Bare ``LauncherHarness`` — no debugger, good for protocol-level tests."""
    h = LauncherHarness()
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()


@pytest.fixture
def dbg_harness():
    """``DebuggerHarness`` — real BDB debugger, ready for end-to-end tests."""
    h = DebuggerHarness()
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()


@pytest.fixture
def dbg_harness_stop_on_entry():
    """``DebuggerHarness`` configured with ``stop_on_entry=True``."""
    h = DebuggerHarness(stop_on_entry=True)
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()
