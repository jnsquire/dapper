"""Regression tests for the 3 security fixes.

Each test class covers one security item from doc/improvement-checklist.md.
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock

import pytest

from dapper.adapter.request_handlers import RequestHandler
from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.debug_utils import format_log_message
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.ipc.connections.tcp import TCPServerConnection
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers
from dapper.shared import debug_shared
from dapper.shared import variable_command_runtime
from dapper.shared.value_conversion import evaluate_with_policy

# ---------------------------------------------------------------------------
# 1. TCP connection warns on non-loopback binding
# ---------------------------------------------------------------------------


class TestTCPLoopbackWarning:
    """TCPServerConnection logs a warning when bound to a non-loopback address."""

    def test_no_warning_for_localhost(self, caplog):

        with caplog.at_level(logging.WARNING):
            conn = TCPServerConnection(host="localhost", port=0)
        assert "SECURITY" not in caplog.text
        assert conn.host == "localhost"

    def test_no_warning_for_127_0_0_1(self, caplog):

        with caplog.at_level(logging.WARNING):
            TCPServerConnection(host="127.0.0.1", port=0)
        assert "SECURITY" not in caplog.text

    def test_no_warning_for_ipv6_loopback(self, caplog):

        with caplog.at_level(logging.WARNING):
            TCPServerConnection(host="::1", port=0)
        assert "SECURITY" not in caplog.text

    def test_warns_for_0_0_0_0(self, caplog):

        with caplog.at_level(logging.WARNING):
            TCPServerConnection(host="0.0.0.0", port=0)
        assert "SECURITY" in caplog.text
        assert "non-loopback" in caplog.text

    def test_warns_for_external_ip(self, caplog):

        with caplog.at_level(logging.WARNING):
            TCPServerConnection(host="192.168.1.100", port=0)
        assert "SECURITY" in caplog.text

    def test_default_host_no_warning(self, caplog):

        with caplog.at_level(logging.WARNING):
            conn = TCPServerConnection(port=0)
        assert "SECURITY" not in caplog.text
        assert conn.host == "localhost"


# ---------------------------------------------------------------------------
# 2. eval() routed through policy checker
# ---------------------------------------------------------------------------


def _make_frame(local_vars: dict | None = None, global_vars: dict | None = None):
    """Create a mock frame with f_locals and f_globals."""
    frame = MagicMock(spec=types.FrameType)
    frame.f_locals = local_vars or {}
    frame.f_globals = global_vars if global_vars is not None else {"__builtins__": {}}
    return frame


def _make_variable_for_tests(dbg, name, value, frame):
    return variable_command_runtime.make_variable_runtime(
        dbg,
        name,
        value,
        frame,
        make_variable_helper=command_handler_helpers.make_variable,
        fallback_make_variable=debug_shared.make_variable_object,
        simple_fn_argcount=command_handlers.SIMPLE_FN_ARGCOUNT,
    )


class TestEvalPolicyEnforcement:
    """All eval() call sites go through the policy checker."""

    def test_inprocess_debugger_set_variable_blocks_import(self):
        dbg = MagicMock()
        dbg.var_refs = {1: (1, "locals")}
        frame = _make_frame({"x": 1})
        dbg.frame_id_to_frame = {1: frame}

        ipd = InProcessDebugger.__new__(InProcessDebugger)
        ipd.debugger = dbg

        result = ipd.set_variable(1, "x", "__import__('os')")
        # Should be blocked by policy (contains "__")
        assert (
            result.get("success") is False
            or "blocked" in str(result.get("message", "")).lower()
            or "error" in str(result.get("message", "")).lower()
        )

    def test_inprocess_debugger_evaluate_blocks_import(self):
        dbg = MagicMock()
        frame = _make_frame({"x": 1})
        dbg.frame_id_to_frame = {1: frame}

        ipd = InProcessDebugger.__new__(InProcessDebugger)
        ipd.debugger = dbg

        result = ipd.evaluate("__import__('os')", frame_id=1)
        # Should be blocked - result is error, not actual os module
        assert result["type"] == "error" or "blocked" in result.get("result", "").lower()

    def test_breakpoint_condition_blocks_import(self):
        resolver = BreakpointResolver()
        frame = _make_frame({"x": 1})

        # Condition with __import__ should be blocked (returns False)
        result = resolver._evaluate_condition("__import__('os')", frame)
        assert result is False

    def test_log_message_blocks_import(self):
        frame = _make_frame({"x": 1})

        # Expression with __import__ should produce <error>
        result = format_log_message("{__import__('os')}", frame)
        assert result == "<error>"

    def test_command_handler_set_scope_blocks_eval_of_import(self):
        frame = _make_frame({"x": 1})

        # Use a conversion function that returns the sentinel so we exercise the eval path
        conversion_failed_sentinel = object()

        def _fail_convert(*_args, **_kwargs):
            return conversion_failed_sentinel

        failing_convert_value_with_context = MagicMock(side_effect=ValueError("fail"))

        result = command_handler_helpers.set_scope_variable(
            frame,
            "locals",
            "x",
            "__import__('os')",
            try_custom_convert=_fail_convert,
            conversion_failed_sentinel=conversion_failed_sentinel,
            evaluate_with_policy_fn=evaluate_with_policy,
            convert_value_with_context_fn=failing_convert_value_with_context,
            logger=command_handlers.logger,
            error_response_fn=command_handlers._error_response,
            conversion_error_message=command_handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: None,
            make_variable_fn=_make_variable_for_tests,
        )
        # Policy blocks it via ValueError; fallback also fails → error
        assert result.get("success") is not True

    def test_policy_allows_safe_expressions(self):

        frame = _make_frame({"x": 42, "y": 10})
        # Simple arithmetic should work
        result = evaluate_with_policy("x + y", frame, allow_builtins=True)
        assert result == 52


# ---------------------------------------------------------------------------
# 3. Module source path validation
# ---------------------------------------------------------------------------


class TestModuleSourcePathValidation:
    """_handle_module_source validates paths before serving."""

    @pytest.fixture
    def handler(self):
        """Create a minimal request handler instance."""

        h = RequestHandler.__new__(RequestHandler)
        h._seq = 0

        def make_response(
            request, command, _response_type=None, *, body=None, success=True, message=None
        ):
            h._seq += 1
            resp = {
                "type": "response",
                "request_seq": request.get("seq", 0),
                "command": command,
                "success": success,
                "seq": h._seq,
            }
            if body:
                resp["body"] = body
            if message:
                resp["message"] = message
            return resp

        h._make_response = make_response
        return h

    @pytest.mark.asyncio
    async def test_rejects_non_python_file(self, handler, monkeypatch, tmp_path):
        """Requesting a module whose __file__ is not .py/.pyw is rejected."""
        # Create a fake .so file
        fake_so = tmp_path / "evil.so"
        fake_so.write_text("binary data")

        fake_mod = types.ModuleType("fake_so_mod")
        fake_mod.__file__ = str(fake_so)

        monkeypatch.setitem(sys.modules, "fake_so_mod", fake_mod)
        try:
            request = {"seq": 1, "arguments": {"moduleId": "fake_so_mod"}}
            resp = await handler._handle_module_source(request)
            assert resp["success"] is False
            assert "not a Python source file" in resp.get("message", "")
        finally:
            monkeypatch.delitem(sys.modules, "fake_so_mod", raising=False)

    @pytest.mark.asyncio
    async def test_accepts_python_file(self, handler, monkeypatch, tmp_path):
        """Requesting a module whose __file__ is a .py file works."""
        fake_py = tmp_path / "good_module.py"
        fake_py.write_text("x = 42\n")

        fake_mod = types.ModuleType("good_test_mod")
        fake_mod.__file__ = str(fake_py)

        monkeypatch.setitem(sys.modules, "good_test_mod", fake_mod)
        try:
            request = {"seq": 1, "arguments": {"moduleId": "good_test_mod"}}
            resp = await handler._handle_module_source(request)
            assert resp["success"] is True
            assert "x = 42" in resp["body"]["content"]
        finally:
            monkeypatch.delitem(sys.modules, "good_test_mod", raising=False)

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_path(self, handler, monkeypatch):
        """Requesting a module whose __file__ doesn't exist is rejected."""
        fake_mod = types.ModuleType("ghost_mod")
        fake_mod.__file__ = "/nonexistent/path/to/module.py"

        monkeypatch.setitem(sys.modules, "ghost_mod", fake_mod)
        try:
            request = {"seq": 1, "arguments": {"moduleId": "ghost_mod"}}
            resp = await handler._handle_module_source(request)
            assert resp["success"] is False
            assert "could not be resolved" in resp.get("message", "")
        finally:
            monkeypatch.delitem(sys.modules, "ghost_mod", raising=False)

    @pytest.mark.asyncio
    async def test_rejects_symlink_to_sensitive_file(self, handler, monkeypatch, tmp_path):
        """A module with __file__ symlinked to a non-.py file is rejected."""
        # Create a sensitive file
        sensitive = tmp_path / "secret.txt"
        sensitive.write_text("secret data")

        # Create a symlink with .py extension pointing to it
        link = tmp_path / "sneaky.py"
        try:
            link.symlink_to(sensitive)
        except OSError:
            pytest.skip("symlinks not supported")

        # The resolved path is .txt, not .py
        fake_mod = types.ModuleType("sneaky_mod")
        fake_mod.__file__ = str(link)

        monkeypatch.setitem(sys.modules, "sneaky_mod", fake_mod)
        try:
            request = {"seq": 1, "arguments": {"moduleId": "sneaky_mod"}}
            resp = await handler._handle_module_source(request)
            # Should succeed because the symlink itself has .py extension
            # and resolves to a real file - but the resolved path's suffix
            # is .txt, so it should be rejected
            assert resp["success"] is False
            assert "not a Python source file" in resp.get("message", "")
        finally:
            monkeypatch.delitem(sys.modules, "sneaky_mod", raising=False)
