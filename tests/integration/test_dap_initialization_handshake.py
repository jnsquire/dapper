"""Integration tests for the DAP initialization handshake sequence.

Verifies the contract between a DAP client (VS Code / TypeScript adapter) and
the Python debug launcher:

    Client              Launcher (Python)
    ──────              ─────────────────
    initialize  ──────►  respond with capabilities + send initialized event
    setBreakpoints ───►  install breakpoints, respond
    configurationDone ─► respond, unblock program execution
                         program starts, hits breakpoints

These tests exercise the real command dispatch path over a local TCP socket
using the binary IPC framing protocol.
"""

from __future__ import annotations

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
# Helpers
# ---------------------------------------------------------------------------


def _make_command_frame(
    command: str, arguments: dict[str, Any] | None = None, *, request_id: int | None = None
) -> bytes:
    """Build a binary IPC frame for a DAP command."""
    payload: dict[str, Any] = {"command": command, "arguments": arguments or {}}
    if request_id is not None:
        payload["id"] = request_id
    return pack_frame(KIND_COMMAND, json.dumps(payload).encode("utf-8"))


def _read_messages(sock: socket.socket, *, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Read all available binary IPC messages from a socket until timeout."""
    messages: list[dict[str, Any]] = []
    sock.settimeout(0.1)
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            # If we already have some messages and nothing new for a beat, stop
            if messages and not buf[HEADER_SIZE:]:
                break
            continue

        # Parse as many complete frames as possible
        while len(buf) >= HEADER_SIZE:
            _kind, length = unpack_header(buf[:HEADER_SIZE])
            if len(buf) < HEADER_SIZE + length:
                break  # incomplete frame, wait for more data
            payload = buf[HEADER_SIZE : HEADER_SIZE + length]
            buf = buf[HEADER_SIZE + length :]
            messages.append(json.loads(payload.decode("utf-8")))
    return messages


def _read_one_message(sock: socket.socket, *, timeout: float = 5.0) -> dict[str, Any]:
    """Read exactly one binary IPC message from a socket."""
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


def _drain_messages(sock: socket.socket, *, timeout: float = 2.0) -> list[dict[str, Any]]:
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


class LauncherHarness:
    """Manages a pair of TCP sockets and a fresh ``DebugSession`` that talks
    the binary IPC protocol, without starting a real Python sub-process."""

    def __init__(self) -> None:
        self.session = debug_shared.DebugSession()
        # TCP listener so the launcher can connect back to us
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", 0))
        self._server_sock.listen(1)
        self.host, self.port = self._server_sock.getsockname()
        # Will be set once the launcher connects
        self.client_sock: socket.socket | None = None
        self._cmd_thread: threading.Thread | None = None

    def connect_session(self) -> None:
        """Wire the session's IPC transport to a TCP socket that points at our
        server socket, then accept the connection."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        # Populate session transport fields (mirrors _setup_ipc_socket)
        self.session.ipc_sock = sock
        self.session.ipc_rfile = sock.makefile("rb", buffering=0)
        self.session.ipc_wfile = sock.makefile("wb", buffering=0)
        self.session.ipc_enabled = True
        self.session.ipc_binary = True
        # Accept the other end so we can read what the launcher sends
        self.client_sock, _ = self._server_sock.accept()

    def start_command_listener(self) -> None:
        """Start the background thread that receives commands from IPC."""
        self._cmd_thread = debug_launcher.start_command_listener(session=self.session)

    def send(self, frame: bytes) -> None:
        """Send a raw IPC frame to the launcher (acting as the adapter)."""
        assert self.client_sock is not None
        self.client_sock.sendall(frame)

    def read_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert self.client_sock is not None
        return _drain_messages(self.client_sock, **kwargs)

    def close(self) -> None:
        self.session.is_terminated = True
        # Shut down sockets so the listener thread sees an error immediately
        for s in (self.client_sock, self.session.ipc_sock):
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        # Wait for the command listener thread to exit
        if self._cmd_thread is not None:
            self._cmd_thread.join(timeout=2.0)
        for s in (self.client_sock, self.session.ipc_sock, self._server_sock):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass


@pytest.fixture
def harness():
    h = LauncherHarness()
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInitializeResponseEchoesId:
    """The 'initialize' response MUST echo the request id so the adapter can
    match it to the pending promise."""

    def test_initialize_response_has_matching_id(self, harness: LauncherHarness):
        harness.send(_make_command_frame("initialize", {}, request_id=42))
        msgs = harness.read_messages(timeout=3)

        responses = [m for m in msgs if m.get("event") == "response"]
        assert responses, f"Expected at least one response, got: {msgs}"
        resp = responses[0]
        assert resp["id"] == 42, f"Response id should be 42, got {resp.get('id')}"
        assert resp["success"] is True

    def test_initialize_response_contains_capabilities(self, harness: LauncherHarness):
        harness.send(_make_command_frame("initialize", {}, request_id=1))
        msgs = harness.read_messages(timeout=3)

        responses = [m for m in msgs if m.get("event") == "response" and m.get("id") == 1]
        assert responses
        body = responses[0].get("body", {})
        assert body.get("supportsConfigurationDoneRequest") is True
        assert body.get("supportsFunctionBreakpoints") is True
        assert body.get("supportsSetVariable") is True


class TestInitializedEventSentAfterInitialize:
    """After responding to 'initialize', the launcher MUST emit an
    'initialized' event so the client knows it can send configuration
    requests (setBreakpoints, etc.)."""

    def test_initialized_event_follows_initialize_response(self, harness: LauncherHarness):
        harness.send(_make_command_frame("initialize", {}, request_id=1))
        msgs = harness.read_messages(timeout=3)

        # Find the response and the initialized event
        response_idx = None
        initialized_idx = None
        for i, m in enumerate(msgs):
            if m.get("event") == "response" and m.get("id") == 1:
                response_idx = i
            elif m.get("event") == "initialized":
                initialized_idx = i

        assert response_idx is not None, f"No initialize response found in {msgs}"
        assert initialized_idx is not None, f"No 'initialized' event found in {msgs}"
        assert initialized_idx > response_idx, (
            f"'initialized' event (idx={initialized_idx}) should follow "
            f"initialize response (idx={response_idx})"
        )


class TestSetBreakpointsResponseId:
    """setBreakpoints response must echo the request id."""

    def test_setbreakpoints_echoes_id(self, harness: LauncherHarness):
        # First: initialize + create a debugger so breakpoint handler has one
        debug_launcher.configure_debugger(False, session=harness.session)
        harness.send(_make_command_frame("initialize", {}, request_id=1))
        harness.read_messages(timeout=2)  # drain

        bp_args = {
            "source": {"path": "/tmp/test_script.py"},
            "breakpoints": [{"line": 5}],
        }
        harness.send(_make_command_frame("setBreakpoints", bp_args, request_id=7))
        msgs = harness.read_messages(timeout=3)

        responses = [m for m in msgs if m.get("event") == "response" and m.get("id") == 7]
        assert responses, f"Expected response with id=7, got: {msgs}"


class TestConfigurationDoneResponseAndEvent:
    """configurationDone must respond with success AND set the
    ``configuration_done_event`` so the launcher can start the program."""

    def test_configuration_done_sets_event(self, harness: LauncherHarness):
        assert not harness.session.configuration_done_event.is_set()

        harness.send(_make_command_frame("configurationDone", {}, request_id=3))
        msgs = harness.read_messages(timeout=3)

        responses = [m for m in msgs if m.get("event") == "response" and m.get("id") == 3]
        assert responses, f"Expected configurationDone response, got: {msgs}"
        assert responses[0]["success"] is True
        assert harness.session.configuration_done_event.is_set(), (
            "configuration_done_event should be set after configurationDone"
        )


class TestFullHandshakeSequence:
    """End-to-end test of the complete DAP initialization handshake:
    initialize → setBreakpoints → configurationDone, verifying correct
    ordering and that the launcher would be unblocked."""

    def test_full_handshake(self, harness: LauncherHarness):
        debug_launcher.configure_debugger(False, session=harness.session)
        all_msgs: list[dict[str, Any]] = []

        # 1) initialize
        harness.send(_make_command_frame("initialize", {}, request_id=1))
        msgs = harness.read_messages(timeout=3)
        all_msgs.extend(msgs)

        # Verify response + initialized event
        init_resp = [m for m in msgs if m.get("event") == "response" and m.get("id") == 1]
        assert init_resp, "Missing initialize response"
        initialized_evts = [m for m in msgs if m.get("event") == "initialized"]
        assert initialized_evts, "Missing 'initialized' event"

        # 2) setBreakpoints
        bp_args = {
            "source": {"path": "/tmp/test_breakpoint.py"},
            "breakpoints": [{"line": 10}, {"line": 20}],
        }
        harness.send(_make_command_frame("setBreakpoints", bp_args, request_id=2))
        msgs = harness.read_messages(timeout=3)
        all_msgs.extend(msgs)

        bp_resp = [m for m in msgs if m.get("event") == "response" and m.get("id") == 2]
        assert bp_resp, "Missing setBreakpoints response"

        # 3) configurationDone
        assert not harness.session.configuration_done_event.is_set()
        harness.send(_make_command_frame("configurationDone", {}, request_id=3))
        msgs = harness.read_messages(timeout=3)
        all_msgs.extend(msgs)

        cd_resp = [m for m in msgs if m.get("event") == "response" and m.get("id") == 3]
        assert cd_resp, "Missing configurationDone response"
        assert harness.session.configuration_done_event.is_set()


class TestLauncherWaitsForConfigurationDone:
    """The launcher's main() must not start the program until
    configurationDone is received. We test this by starting the
    run_with_debugger path in a thread and verifying it blocks until
    the event is set."""

    def test_run_blocks_until_configuration_done(self, harness: LauncherHarness, tmp_path):
        debug_launcher.configure_debugger(False, session=harness.session)

        execution_started = threading.Event()
        execution_finished = threading.Event()

        # Create a real temp file so run_with_debugger can open it
        script = tmp_path / "test_script.py"
        script.write_text("x = 1\n")

        def _fake_run(code, globs=None):
            execution_started.set()

        assert harness.session.debugger is not None
        # debugger is typed as Optional; narrowing ensures safe attribute access
        harness.session.debugger.run = _fake_run  # type: ignore[attr-defined]

        # Simulate the launcher's main() waiting logic in a thread
        def _launcher_thread():
            harness.session.configuration_done_event.wait(timeout=10)
            debug_launcher.run_with_debugger(str(script), [], session=harness.session)
            execution_finished.set()

        t = threading.Thread(target=_launcher_thread, daemon=True)
        t.start()

        # Program should NOT have started yet
        time.sleep(0.3)
        assert not execution_started.is_set(), "Program started before configurationDone was sent!"

        # Now send configurationDone
        harness.send(_make_command_frame("configurationDone", {}, request_id=99))
        harness.read_messages(timeout=2)  # drain response

        # Now the program should start
        assert execution_started.wait(timeout=5), (
            "Program did not start after configurationDone was sent"
        )
        execution_finished.wait(timeout=5)

    def test_breakpoints_are_installed_before_program_runs(
        self, harness: LauncherHarness, tmp_path
    ):
        """Breakpoints sent between initialize and configurationDone must
        be installed before the debugger's run() is called."""
        debug_launcher.configure_debugger(False, session=harness.session)

        # Create a real temp file
        script = tmp_path / "bp_test.py"
        script.write_text("x = 1\ny = 2\nz = 3\n" * 10)
        script_path = str(script)

        breakpoints_at_run_time: list[Any] = []

        def _capturing_run(code, globs=None):
            # Snapshot what breakpoints are set at the time run() is called
            dbg = harness.session.debugger
            # get_all_breaks returns {filename: [line, ...]}
            try:
                # dbg may be Optional; guard for static analyzer
                if dbg is None:
                    breakpoints_at_run_time.append("none")
                else:
                    breakpoints_at_run_time.append(dict(dbg.get_all_breaks()))  # type: ignore[attr-defined]
            except Exception:
                breakpoints_at_run_time.append("error")

        assert harness.session.debugger is not None
        harness.session.debugger.run = _capturing_run  # type: ignore[attr-defined]

        done = threading.Event()

        def _launcher_thread():
            harness.session.configuration_done_event.wait(timeout=10)
            debug_launcher.run_with_debugger(script_path, [], session=harness.session)
            done.set()

        t = threading.Thread(target=_launcher_thread, daemon=True)
        t.start()

        # Send the full handshake: initialize → setBreakpoints → configurationDone
        harness.send(_make_command_frame("initialize", {}, request_id=1))
        harness.read_messages(timeout=2)

        bp_args = {
            "source": {"path": script_path},
            "breakpoints": [{"line": 5}, {"line": 15}],
        }
        harness.send(_make_command_frame("setBreakpoints", bp_args, request_id=2))
        harness.read_messages(timeout=2)

        harness.send(_make_command_frame("configurationDone", {}, request_id=3))
        harness.read_messages(timeout=2)

        assert done.wait(timeout=5), "Launcher thread didn't finish"
        assert breakpoints_at_run_time, "run() was never called"
        bp_snapshot = breakpoints_at_run_time[0]
        assert isinstance(bp_snapshot, dict), f"Unexpected snapshot: {bp_snapshot}"
        assert script_path in bp_snapshot, (
            f"Breakpoints for {script_path} not found: {bp_snapshot}"
        )
        assert 5 in bp_snapshot[script_path]
        assert 15 in bp_snapshot[script_path]


class TestIdNotPresentStillWorks:
    """Commands without an id (fire-and-forget) should still be handled
    without crashing."""

    def test_initialize_without_id(self, harness: LauncherHarness):
        harness.send(_make_command_frame("initialize", {}))
        msgs = harness.read_messages(timeout=3)
        # Should get a response (without id) and an initialized event
        initialized = [m for m in msgs if m.get("event") == "initialized"]
        assert initialized, f"Expected 'initialized' event even without request id: {msgs}"

    def test_configuration_done_without_id(self, harness: LauncherHarness):
        harness.send(_make_command_frame("configurationDone", {}))
        time.sleep(0.5)
        assert harness.session.configuration_done_event.is_set()


class TestMultipleRequestsGetCorrectIds:
    """When multiple requests are in flight, each response must echo its
    own request id — not the id of any other request."""

    def test_interleaved_ids(self, harness: LauncherHarness):
        debug_launcher.configure_debugger(False, session=harness.session)

        harness.send(_make_command_frame("initialize", {}, request_id=100))
        msgs = harness.read_messages(timeout=3)
        resp_100 = [m for m in msgs if m.get("event") == "response" and m.get("id") == 100]
        assert resp_100

        harness.send(
            _make_command_frame(
                "setBreakpoints",
                {
                    "source": {"path": "/tmp/a.py"},
                    "breakpoints": [{"line": 1}],
                },
                request_id=200,
            )
        )
        harness.send(_make_command_frame("configurationDone", {}, request_id=300))

        msgs = harness.read_messages(timeout=3)
        ids_seen = {m["id"] for m in msgs if m.get("event") == "response" and "id" in m}
        assert 200 in ids_seen, f"Missing response for id=200. Seen: {ids_seen}"
        assert 300 in ids_seen, f"Missing response for id=300. Seen: {ids_seen}"
        # No cross-contamination
        assert 100 not in ids_seen, "Response for id=100 should not appear in second batch"
