"""Tests for just-my-code filtering (``dapper.core.just_my_code``)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from dapper.config.dapper_config import DapperConfig
from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.debugger_bdb import _annotate_library_frames
from dapper.core.just_my_code import is_user_frame
from dapper.core.just_my_code import is_user_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_frame(filename: str) -> Any:
    """Return a minimal fake frame with the given co_filename."""
    code = SimpleNamespace(co_filename=filename)
    return SimpleNamespace(f_code=code)


# ---------------------------------------------------------------------------
# is_user_path
# ---------------------------------------------------------------------------


class TestIsUserPath:
    def test_regular_user_file_is_user(self):
        assert is_user_path("/home/user/project/app.py") is True

    def test_relative_user_file_is_user(self):
        assert is_user_path("mypackage/utils.py") is True

    def test_frozen_module_is_library(self):
        assert is_user_path("<frozen importlib._bootstrap>") is False

    def test_bare_frozen_is_library(self):
        assert is_user_path("<frozen>") is False

    def test_site_packages_is_library(self):
        assert is_user_path("/usr/lib/python3.12/site-packages/requests/api.py") is False

    def test_dist_packages_is_library(self):
        assert is_user_path("/usr/lib/python3/dist-packages/urllib3/util.py") is False

    def test_windows_site_packages_is_library(self):
        # Normalised forward slashes
        assert is_user_path(r"C:\Python312\Lib\site-packages\flask\app.py") is False

    def test_dapper_core_is_library(self):
        assert is_user_path("/project/dapper/core/debugger_bdb.py") is False

    def test_dapper_launcher_is_library(self):
        assert is_user_path("/project/dapper/launcher/debug_launcher.py") is False

    def test_stdlib_inside_prefix_is_library(self):
        # Build a path that is inside sys.prefix
        prefix_path = sys.prefix.replace("\\", "/")
        stdlib_file = prefix_path + "/lib/python3.12/os.py"
        assert is_user_path(stdlib_file) is False

    def test_case_insensitive_site_packages(self):
        assert is_user_path("/env/Lib/site-packages/numpy/__init__.py") is False

    def test_empty_string_is_user(self):
        # Empty string has no known-library markers; treated as user.
        assert is_user_path("") is True


# ---------------------------------------------------------------------------
# is_user_frame
# ---------------------------------------------------------------------------


class TestIsUserFrame:
    def test_delegates_to_is_user_path(self):
        frame = _fake_frame("/home/user/project/app.py")
        assert is_user_frame(frame) is True  # type: ignore[arg-type]

    def test_library_frame_detected(self):
        frame = _fake_frame("/env/lib/python3.12/site-packages/requests/api.py")
        assert is_user_frame(frame) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DapperConfig.just_my_code
# ---------------------------------------------------------------------------


class TestDapperConfigJustMyCode:
    def test_default_is_true(self):
        cfg = DapperConfig()
        assert cfg.just_my_code is True

    def test_from_launch_request_default(self):
        req = {
            "seq": 1,
            "command": "launch",
            "type": "request",
            "arguments": {"program": "/tmp/app.py"},
        }
        cfg = DapperConfig.from_launch_request(req)  # type: ignore[arg-type]
        assert cfg.just_my_code is True

    def test_from_launch_request_explicit_false(self):
        req = {
            "seq": 1,
            "command": "launch",
            "type": "request",
            "arguments": {"program": "/tmp/app.py", "justMyCode": False},
        }
        cfg = DapperConfig.from_launch_request(req)  # type: ignore[arg-type]
        assert cfg.just_my_code is False

    def test_from_attach_request_default(self):
        req = {
            "seq": 1,
            "command": "attach",
            "type": "request",
            "arguments": {},
        }
        cfg = DapperConfig.from_attach_request(req)  # type: ignore[arg-type]
        assert cfg.just_my_code is True

    def test_from_attach_request_explicit_false(self):
        req = {
            "seq": 1,
            "command": "attach",
            "type": "request",
            "arguments": {"justMyCode": False},
        }
        cfg = DapperConfig.from_attach_request(req)  # type: ignore[arg-type]
        assert cfg.just_my_code is False


# ---------------------------------------------------------------------------
# DebuggerBDB.just_my_code stepping behaviour
# ---------------------------------------------------------------------------


class TestDebuggerBDBJustMyCode:
    """Confirm that user_line skips library frames when just_my_code=True."""

    def _make_dbg(self, just_my_code: bool = True) -> tuple[DebuggerBDB, list]:
        messages: list = []
        dbg = DebuggerBDB(
            send_message=lambda event, **kw: messages.append((event, kw)),
            just_my_code=just_my_code,
        )
        return dbg, messages

    def _frame(self, filename: str, lineno: int = 1) -> Any:
        code = SimpleNamespace(
            co_filename=filename,
            co_name="<module>",
            co_firstlineno=1,
        )
        return SimpleNamespace(
            f_code=code,
            f_lineno=lineno,
            f_locals={},
            f_back=None,
            f_globals={},
        )

    def test_library_frame_skipped_when_just_my_code_enabled(self):
        dbg, _messages = self._make_dbg(just_my_code=True)
        lib_frame = self._frame("/env/lib/python3.12/site-packages/requests/api.py")

        skipped = False

        def _set_step():
            nonlocal skipped
            skipped = True

        dbg.set_step = _set_step  # type: ignore[method-assign]

        dbg.user_line(lib_frame)  # type: ignore[arg-type]

        assert skipped, "set_step should be called for library frames"
        assert not _messages, "no stopped event should be emitted for library frames"

    def test_library_frame_not_skipped_when_just_my_code_disabled(self):
        dbg, _messages = self._make_dbg(just_my_code=False)
        lib_frame = self._frame("/env/lib/python3.12/site-packages/requests/api.py")

        skipped = False

        def _set_step():
            nonlocal skipped
            skipped = True

        # Also stub _emit_stopped_event so the test doesn't need a full server.
        dbg.set_step = _set_step  # type: ignore[method-assign]

        stopped = False

        def _emit(frame, thread_id, reason, description=None):
            nonlocal stopped
            stopped = True

        dbg._emit_stopped_event = _emit  # type: ignore[method-assign]

        dbg.user_line(lib_frame)  # type: ignore[arg-type]

        assert not skipped, "library frame should not be skipped when just_my_code=False"

    def test_user_frame_not_skipped_when_just_my_code_enabled(self):
        dbg, _messages = self._make_dbg(just_my_code=True)
        user_frame = self._frame("/home/user/project/app.py")

        skipped = False

        def _set_step():
            nonlocal skipped
            skipped = True

        dbg.set_step = _set_step  # type: ignore[method-assign]

        stopped = False

        def _emit(frame, thread_id, reason, description=None):
            nonlocal stopped
            stopped = True

        dbg._emit_stopped_event = _emit  # type: ignore[method-assign]

        dbg.user_line(user_frame)  # type: ignore[arg-type]

        assert not skipped, "user frame should not be skipped"

    def test_constructor_default_just_my_code(self):
        dbg = DebuggerBDB()
        assert dbg.just_my_code is True

    def test_constructor_just_my_code_false(self):
        dbg = DebuggerBDB(just_my_code=False)
        assert dbg.just_my_code is False


# ---------------------------------------------------------------------------
# _annotate_library_frames
# ---------------------------------------------------------------------------


class TestAnnotateLibraryFrames:
    """_annotate_library_frames marks library frames with presentationHint subtle."""

    def _stack_frame(self, path: str) -> dict:
        return {"id": 1, "name": "fn", "line": 1, "column": 0, "source": {"path": path}}

    def test_library_frame_gets_subtle_hint(self):
        frames = [self._stack_frame("/env/lib/python3.12/site-packages/requests/api.py")]
        _annotate_library_frames(frames)
        assert frames[0].get("presentationHint") == "subtle"

    def test_user_frame_not_annotated(self):
        frames = [self._stack_frame("/home/user/project/app.py")]
        _annotate_library_frames(frames)
        assert "presentationHint" not in frames[0]

    def test_frame_without_source_unchanged(self):
        frames = [{"id": 1, "name": "fn", "line": 1, "column": 0}]
        _annotate_library_frames(frames)
        assert "presentationHint" not in frames[0]

    def test_mixed_frames(self):
        frames = [
            self._stack_frame("/home/user/project/app.py"),
            self._stack_frame("/env/lib/python3.12/site-packages/requests/api.py"),
            self._stack_frame("/home/user/project/utils.py"),
        ]
        _annotate_library_frames(frames)
        assert "presentationHint" not in frames[0]
        assert frames[1].get("presentationHint") == "subtle"
        assert "presentationHint" not in frames[2]
