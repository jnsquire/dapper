"""Comprehensive DAP integration tests exercising real DebuggerBDB workloads.

These tests use ``DebuggerHarness`` which wires a real ``DebuggerBDB`` to a
local TCP socket pair.  Each test acts as the DAP client:

    Test (client)           Harness (launcher + BDB)
    ─────────────           ────────────────────────
    initialize  ──────────►  capabilities + initialized
    setBreakpoints ───────►  install breakpoints via BDB
    configurationDone ────►  unblock, dbg.run(script)
       ◄──── stopped event (breakpoint hit)
    threads / stackTrace ──► inspect state
    scopes / variables ────► drill-down
    continue / next / … ──►  resume

Test classes mirror the plan:
- TestBreakpointConfiguration   — line, function, exception BPs
- TestStoppedStateInspection    — threads → stackTrace → scopes → variables
- TestVariableMutation          — setVariable, evaluate with side effects
- TestStepping                  — next, stepIn, stepOut, continue
- TestSessionLifecycle          — terminate, disconnect
- TestErrorPaths                — bad commands, missing debugger, etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.dap_test_harness import DebuggerHarness
from tests.integration.dap_test_harness import LauncherHarness
from tests.integration.dap_test_harness import responses

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fixture(name: str) -> str:
    """Return the absolute path to a fixture script."""
    p = FIXTURES / name
    assert p.exists(), f"Fixture not found: {p}"
    return str(p)


def _get_response(msgs: list[dict], rid: int) -> dict:
    """Get the response with the given *rid*, or fail."""
    rs = responses(msgs, request_id=rid)
    assert rs, f"No response with id={rid}.  Got: {msgs}"
    return rs[0]


# ---------------------------------------------------------------------------
# TestBreakpointConfiguration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBreakpointConfiguration:
    """Setting breakpoints via the DAP protocol and having BDB honour them."""

    def test_line_breakpoint_hit(self, dbg_harness: DebuggerHarness):
        """A line breakpoint on a simple assignment stops the program."""
        script = _fixture("simple_assign.py")
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [4]})
        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped["reason"] == "breakpoint"

        # Resume so the debugger thread finishes cleanly
        dbg_harness.send_continue(stopped.get("threadId", 0))
        dbg_harness.wait_for_runner(timeout=10)

    def test_multiple_breakpoints_in_one_file(self, dbg_harness: DebuggerHarness):
        """Two breakpoints in the same file both fire in order."""
        script = _fixture("simple_assign.py")
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [3, 5]})

        # First stop
        stopped1 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped1["reason"] == "breakpoint"
        dbg_harness.send_continue(stopped1.get("threadId", 0))

        # Second stop
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "breakpoint"
        dbg_harness.send_continue(stopped2.get("threadId", 0))

        dbg_harness.wait_for_runner(timeout=10)

    def test_breakpoint_in_function_body(self, dbg_harness: DebuggerHarness):
        """A breakpoint inside a function body fires when the function runs."""
        script = _fixture("function_calls.py")
        # line 3 is `result = a + b` inside add()
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [3]})

        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped["reason"] == "breakpoint"
        dbg_harness.send_continue(stopped.get("threadId", 0))

        # add() is called twice (line 10 and line 12) so we get a second stop
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "breakpoint"
        dbg_harness.send_continue(stopped2.get("threadId", 0))

        dbg_harness.wait_for_runner(timeout=10)

    def test_setbreakpoints_response_body(self, dbg_harness: DebuggerHarness):
        """The setBreakpoints response includes a ``breakpoints`` body array
        with ``verified`` status for each requested breakpoint."""
        script = _fixture("simple_assign.py")
        dbg_harness.configure_debugger()

        # initialize
        _rid_init, msgs = dbg_harness.send_and_collect_response("initialize")
        dbg_harness.read_messages(timeout=1)

        # setBreakpoints
        bp_args = {
            "source": {"path": script},
            "breakpoints": [{"line": 3}, {"line": 5}],
        }
        rid_bp, msgs = dbg_harness.send_and_collect_response("setBreakpoints", bp_args)
        resp = _get_response(msgs, rid_bp)
        assert resp["success"] is True
        body = resp.get("body", {})
        bps = body.get("breakpoints", [])
        assert len(bps) == 2
        for bp in bps:
            assert bp.get("verified") is True

        # configurationDone
        dbg_harness.send_and_collect_response("configurationDone")
        dbg_harness.run_script(script)

        # Let it stop/continue
        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        dbg_harness.send_continue(stopped.get("threadId", 0))
        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        dbg_harness.send_continue(stopped.get("threadId", 0))
        dbg_harness.wait_for_runner(timeout=10)

    def test_function_breakpoint(self, dbg_harness: DebuggerHarness):
        """Function breakpoints via setFunctionBreakpoints stop on call."""
        script = _fixture("function_calls.py")
        dbg_harness.configure_debugger()

        # Handshake
        dbg_harness.send_and_collect_response("initialize")
        dbg_harness.read_messages(timeout=1)

        # setFunctionBreakpoints
        fbp_args = {"breakpoints": [{"name": "multiply"}]}
        _rid, _msgs = dbg_harness.send_and_collect_response("setFunctionBreakpoints", fbp_args)

        dbg_harness.send_and_collect_response("configurationDone")
        dbg_harness.run_script(script)

        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped["reason"] == "function breakpoint"
        dbg_harness.send_continue(stopped.get("threadId", 0))
        dbg_harness.wait_for_runner(timeout=10)

    def test_exception_breakpoint_on_raised(self, dbg_harness: DebuggerHarness):
        """Exception breakpoints fire when a matching exception is raised."""
        script = _fixture("exception_demo.py")
        dbg_harness.configure_debugger()

        # Handshake
        dbg_harness.send_and_collect_response("initialize")
        dbg_harness.read_messages(timeout=1)

        # setExceptionBreakpoints
        exc_args = {"filters": ["raised"]}
        dbg_harness.send_and_collect_response("setExceptionBreakpoints", exc_args)

        dbg_harness.send_and_collect_response("configurationDone")
        dbg_harness.run_script(script)

        stopped = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped["reason"] == "exception"
        dbg_harness.send_continue(stopped.get("threadId", 0))

        # The "raised" filter may fire multiple times as the exception
        # propagates through frames.  Keep resuming until the script ends.
        while not dbg_harness._runner_done.wait(timeout=0.5):
            try:
                extra = dbg_harness.wait_for_event("stopped", timeout=1)
                dbg_harness.send_continue(extra.get("threadId", 0))
            except AssertionError:  # noqa: PERF203
                break

        dbg_harness.wait_for_runner(timeout=5)


# ---------------------------------------------------------------------------
# TestStoppedStateInspection
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoppedStateInspection:
    """When the debugger is stopped, the DAP inspection waterfall
    (threads → stackTrace → scopes → variables) must return meaningful data."""

    def _stop_at(self, harness: DebuggerHarness, script: str, line: int) -> dict:
        """Send handshake, run script, wait for stop at *line*."""
        harness.run_script_after_handshake(script, breakpoints={script: [line]})
        return harness.wait_for_event("stopped", timeout=10)

    def test_threads_returns_at_least_one(self, dbg_harness: DebuggerHarness):
        script = _fixture("simple_assign.py")
        stopped = self._stop_at(dbg_harness, script, 4)

        rid, msgs = dbg_harness.send_and_collect_response("threads")
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        body = resp.get("body", {})
        threads = body.get("threads", [])
        assert len(threads) >= 1

        dbg_harness.send_continue(stopped.get("threadId", 0))
        dbg_harness.wait_for_runner(timeout=10)

    def test_stack_trace_has_frames(self, dbg_harness: DebuggerHarness):
        """stackTrace at a function breakpoint includes the function frame."""
        script = _fixture("call_stack.py")
        # Stop inside level3() at line 3
        stopped = self._stop_at(dbg_harness, script, 3)
        tid = stopped.get("threadId", 0)

        rid, msgs = dbg_harness.send_and_collect_response("stackTrace", {"threadId": tid})
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        frames = resp.get("body", {}).get("stackFrames", [])
        assert len(frames) >= 3  # level3 → level2 → level1 (+ possibly module)
        # Top frame should be in level3
        top = frames[0]
        assert top.get("line") == 3
        assert "level3" in top.get("name", "")

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)

    def test_scopes_and_variables_waterfall(self, dbg_harness: DebuggerHarness):
        """scopes → variables returns local variables at the stopped frame."""
        script = _fixture("nested_vars.py")
        # Stop at line 7 where all variables are defined
        stopped = self._stop_at(dbg_harness, script, 7)
        tid = stopped.get("threadId", 0)

        # stackTrace to get frameId
        rid, msgs = dbg_harness.send_and_collect_response("stackTrace", {"threadId": tid})
        frames = _get_response(msgs, rid).get("body", {}).get("stackFrames", [])
        assert frames
        frame_id = frames[0]["id"]

        # scopes
        rid, msgs = dbg_harness.send_and_collect_response("scopes", {"frameId": frame_id})
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        scopes = resp.get("body", {}).get("scopes", [])
        assert scopes  # at least one scope (Locals)
        local_scope = scopes[0]
        var_ref = local_scope.get("variablesReference")
        assert var_ref is not None
        assert var_ref != 0

        # variables for the local scope
        rid, msgs = dbg_harness.send_and_collect_response(
            "variables", {"variablesReference": var_ref}
        )
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        variables = resp.get("body", {}).get("variables", [])
        var_names = {v["name"] for v in variables}
        # We expect at least name, age, scores, person, nested
        for expected in ("name", "age", "scores", "person", "nested"):
            assert expected in var_names, (
                f"Expected variable {expected!r} in scope.  Got: {var_names}"
            )

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)


# ---------------------------------------------------------------------------
# TestVariableMutation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestVariableMutation:
    """setVariable and evaluate with side effects mutate program state."""

    def _stop_at(self, harness: DebuggerHarness, script: str, line: int) -> dict:
        harness.run_script_after_handshake(script, breakpoints={script: [line]})
        return harness.wait_for_event("stopped", timeout=10)

    def _get_frame_and_scope(self, harness: DebuggerHarness, tid: int):
        """Return (frame_id, variablesReference) for the Locals scope."""
        rid, msgs = harness.send_and_collect_response("stackTrace", {"threadId": tid})
        frames = _get_response(msgs, rid)["body"]["stackFrames"]
        frame_id = frames[0]["id"]

        rid, msgs = harness.send_and_collect_response("scopes", {"frameId": frame_id})
        scopes = _get_response(msgs, rid)["body"]["scopes"]
        return frame_id, scopes[0]["variablesReference"]

    def test_evaluate_expression(self, dbg_harness: DebuggerHarness):
        """evaluate returns the result of a Python expression at the stopped frame."""
        script = _fixture("simple_assign.py")
        stopped = self._stop_at(dbg_harness, script, 5)
        tid = stopped.get("threadId", 0)

        frame_id, _ = self._get_frame_and_scope(dbg_harness, tid)

        rid, msgs = dbg_harness.send_and_collect_response(
            "evaluate",
            {"expression": "x + y", "frameId": frame_id, "context": "watch"},
        )
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        # x=1, y=2 → 3
        assert resp["body"]["result"] == "3"

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)


# ---------------------------------------------------------------------------
# TestStepping
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStepping:
    """next, stepIn, stepOut advance execution and emit stopped events."""

    def _stop_at(self, harness: DebuggerHarness, script: str, line: int) -> dict:
        harness.run_script_after_handshake(script, breakpoints={script: [line]})
        return harness.wait_for_event("stopped", timeout=10)

    def test_next_advances_one_line(self, dbg_harness: DebuggerHarness):
        """'next' steps to the next statement in the same frame."""
        script = _fixture("simple_assign.py")
        stopped = self._stop_at(dbg_harness, script, 3)
        tid = stopped.get("threadId", 0)

        dbg_harness.send_command("next", {"threadId": tid})
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "step"

        # Verify we're now on line 4 via stackTrace
        rid, msgs = dbg_harness.send_and_collect_response("stackTrace", {"threadId": tid})
        frames = _get_response(msgs, rid)["body"]["stackFrames"]
        assert frames[0]["line"] == 4

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)

    def test_step_in_enters_function(self, dbg_harness: DebuggerHarness):
        """'stepIn' on a call expression descends into the callee."""
        script = _fixture("function_calls.py")
        # Stop at line 10: x = add(10, 20)
        stopped = self._stop_at(dbg_harness, script, 10)
        tid = stopped.get("threadId", 0)

        dbg_harness.send_command("stepIn", {"threadId": tid})
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "step"

        # Should now be inside add(), on line 3
        rid, msgs = dbg_harness.send_and_collect_response("stackTrace", {"threadId": tid})
        frames = _get_response(msgs, rid)["body"]["stackFrames"]
        top = frames[0]
        assert "add" in top.get("name", "")

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)

    def test_step_out_returns_to_caller(self, dbg_harness: DebuggerHarness):
        """'stepOut' from inside a function returns to the caller."""
        script = _fixture("function_calls.py")
        # Stop inside add() at line 3
        stopped = self._stop_at(dbg_harness, script, 3)
        tid = stopped.get("threadId", 0)

        dbg_harness.send_command("stepOut", {"threadId": tid})
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "step"

        # Should now be back in the module-level code
        rid, msgs = dbg_harness.send_and_collect_response("stackTrace", {"threadId": tid})
        frames = _get_response(msgs, rid)["body"]["stackFrames"]
        top = frames[0]
        # After stepping out of add() called from line 10, we land on line 10 or 11
        assert top.get("line", 0) >= 10

        # Clear breakpoints before continuing so the second call to add()
        # on line 12 doesn't re-trigger the breakpoint at line 3.
        dbg_harness.send_and_collect_response(
            "setBreakpoints",
            {"source": {"path": script}, "breakpoints": []},
        )

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)

    def test_continue_runs_to_next_breakpoint(self, dbg_harness: DebuggerHarness):
        """'continue' resumes and stops at the next breakpoint."""
        script = _fixture("simple_assign.py")
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [3, 5]})

        stopped1 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped1["reason"] == "breakpoint"
        tid = stopped1.get("threadId", 0)

        dbg_harness.send_continue(tid)
        stopped2 = dbg_harness.wait_for_event("stopped", timeout=10)
        assert stopped2["reason"] == "breakpoint"

        dbg_harness.send_continue(tid)
        dbg_harness.wait_for_runner(timeout=10)


# ---------------------------------------------------------------------------
# TestSessionLifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSessionLifecycle:
    """terminate and disconnect end the session cleanly."""

    def test_terminate_sets_flag(self, dbg_harness: DebuggerHarness):
        """The terminate command marks the session as terminated."""
        script = _fixture("simple_assign.py")
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [4]})

        dbg_harness.wait_for_event("stopped", timeout=10)

        rid, msgs = dbg_harness.send_and_collect_response("terminate")
        resp = _get_response(msgs, rid)
        assert resp["success"] is True
        assert dbg_harness.session.is_terminated is True

    def test_disconnect_after_stop(self, dbg_harness: DebuggerHarness):
        """Sending disconnect while stopped ends the session."""
        script = _fixture("simple_assign.py")
        dbg_harness.run_script_after_handshake(script, breakpoints={script: [4]})

        dbg_harness.wait_for_event("stopped", timeout=10)
        rid = dbg_harness.send_command("disconnect", {})
        msgs = dbg_harness.read_messages(timeout=3)
        # We should get a response (success or otherwise)
        rs = responses(msgs, request_id=rid)
        assert rs


# ---------------------------------------------------------------------------
# TestErrorPaths
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestErrorPaths:
    """Invalid commands and edge cases produce proper error responses."""

    def test_unknown_command_returns_error(self, harness: LauncherHarness):
        """An unrecognised command returns success=False."""
        rid = harness.send_command("totallyBogusCommand", {})
        msgs = harness.read_messages(timeout=3)
        resp = _get_response(msgs, rid)
        assert resp["success"] is False
        assert "Unknown command" in resp.get("message", "")

    def test_stack_trace_without_debugger(self, harness: LauncherHarness):
        """stackTrace without a debugger returns a response (no crash)."""
        # Don't configure a debugger — the handlers should guard on _active_debugger()
        rid = harness.send_command("stackTrace", {"threadId": 1})
        msgs = harness.read_messages(timeout=3)
        # Should get some response (default success ack), not a crash
        resp = _get_response(msgs, rid)
        assert resp.get("success") is True  # default ack

    def test_goto_without_debugger(self, harness: LauncherHarness):
        """goto without a debugger returns an error response."""
        rid = harness.send_command("goto", {"threadId": 1, "targetId": 5})
        msgs = harness.read_messages(timeout=3)
        resp = _get_response(msgs, rid)
        assert resp["success"] is False

    def test_goto_targets_missing_params(self, harness: LauncherHarness):
        """gotoTargets with missing frameId/line returns error."""
        from dapper.launcher import debug_launcher  # noqa: PLC0415

        debug_launcher.configure_debugger(False, session=harness.session)

        rid = harness.send_command("gotoTargets", {})
        msgs = harness.read_messages(timeout=3)
        resp = _get_response(msgs, rid)
        assert resp["success"] is False

    def test_evaluate_without_stopped_frame(self, dbg_harness: DebuggerHarness):
        """evaluate when no frame is stopped handles gracefully."""
        dbg_harness.configure_debugger()
        dbg_harness.send_and_collect_response("initialize")
        dbg_harness.read_messages(timeout=1)

        rid = dbg_harness.send_command("evaluate", {"expression": "1+1", "context": "repl"})
        msgs = dbg_harness.read_messages(timeout=3)
        # Should get some response—the main thing is it doesn't crash/hang
        resp = _get_response(msgs, rid)
        assert "success" in resp


# ---------------------------------------------------------------------------
# TestStopOnEntry
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStopOnEntry:
    """When stop_on_entry is set the debugger should stop before the first line."""

    def test_stop_on_entry(self):
        """The debugger stops before the first user statement."""
        h = DebuggerHarness(stop_on_entry=True)
        h.connect_session()
        h.start_command_listener()
        try:
            script = _fixture("simple_assign.py")
            h.configure_debugger()
            h.do_handshake()
            h.run_script(script)

            stopped = h.wait_for_event("stopped", timeout=10)
            # Reason should indicate "entry" or "step" (BDB-implementation specific)
            assert stopped["reason"] in ("entry", "step")

            h.send_continue(stopped.get("threadId", 0))
            h.wait_for_runner(timeout=10)
        finally:
            h.close()


# ---------------------------------------------------------------------------
# Fixtures (imported from the shared harness module)
# ---------------------------------------------------------------------------


@pytest.fixture
def harness():
    h = LauncherHarness()
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()


@pytest.fixture
def dbg_harness():
    h = DebuggerHarness()
    h.connect_session()
    h.start_command_listener()
    yield h
    h.close()
