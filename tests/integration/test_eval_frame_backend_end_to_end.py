from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap

import pytest


def _skip_if_unavailable(payload: dict[str, object]) -> None:
    skipped = payload.get("skipped")
    if isinstance(skipped, str):
        pytest.skip(skipped)


def test_eval_frame_backend_breakpoint_dispatches_stopped_event_end_to_end() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import json
        from unittest.mock import MagicMock

        from dapper._frame_eval import CYTHON_AVAILABLE
        from dapper._frame_eval import types as frame_types
        from dapper._frame_eval._frame_evaluator import _collect_code_lines
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.frame_eval_main import frame_eval_manager
        from dapper._frame_eval.frame_eval_main import shutdown_frame_eval
        from dapper.core.debugger_bdb import DebuggerBDB

        messages = []


        def send_message(event, **body):
            messages.append([event, body])


        def diff_stats(before, after):
            keys = (
                "slow_path_attempts",
                "slow_path_activations",
                "scoped_trace_installs",
                "return_events",
                "exception_events",
            )
            return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


        def sample_function():
            alpha = 1
            beta = 2
            gamma = alpha + beta
            return gamma


        if not CYTHON_AVAILABLE:
            print(json.dumps({"skipped": "cython unavailable"}, sort_keys=True))
            raise SystemExit(0)

        setup_ok = False
        integrated = False
        result = None
        runtime_status = None
        backend_stats = None
        stats_delta = None

        try:
            setup_ok = frame_eval_manager.setup_frame_eval(
                {"enabled": True, "backend": "EVAL_FRAME"}
            )
            backend = frame_eval_manager.active_backend
            runtime_status = frame_eval_manager.get_debug_info()["runtime_status"]

            if runtime_status.backend_type != "EvalFrameBackend":
                print(
                    json.dumps(
                        {
                            "backend_type": runtime_status.backend_type,
                            "skipped": f"eval-frame backend unavailable in this runtime (selected {runtime_status.backend_type})",
                        },
                        sort_keys=True,
                    )
                )
                raise SystemExit(0)

            debugger = DebuggerBDB(send_message=send_message)
            debugger.reset()
            debugger.process_commands = MagicMock()

            lines = sorted(_collect_code_lines(sample_function.__code__))
            target_line = lines[1] if len(lines) > 1 else lines[0]
            debugger.set_break(sample_function.__code__.co_filename, target_line)
            backend.update_breakpoints(sample_function.__code__.co_filename, set(lines))

            stats_before = frame_types.get_frame_eval_stats()
            integrated = integrate_with_backend(backend, debugger)
            result = sample_function()
            stats_after = frame_types.get_frame_eval_stats()

            runtime_status = frame_eval_manager.get_debug_info()["runtime_status"]
            backend_stats = backend.get_statistics()
            stats_delta = diff_stats(stats_before, stats_after)

            print(
                json.dumps(
                    {
                        "backend_stats": backend_stats,
                        "backend_type": runtime_status.backend_type,
                        "hook_installed": runtime_status.hook_installed,
                        "integrated": integrated,
                        "line_count": len(lines),
                        "messages": messages,
                        "result": result,
                        "setup_ok": setup_ok,
                        "stats_delta": stats_delta,
                    },
                    sort_keys=True,
                )
            )
        finally:
            shutdown_frame_eval()
        """
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr or result.stdout

    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert stdout_lines, result.stderr

    payload = json.loads(stdout_lines[-1])
    _skip_if_unavailable(payload)

    assert payload["setup_ok"] is True
    assert payload["integrated"] is True
    assert payload["backend_type"] == "EvalFrameBackend"
    assert payload["hook_installed"] is True
    assert payload["result"] == 3
    assert payload["backend_stats"]["installed"] is True
    assert payload["backend_stats"]["breakpoint_files"] == 1
    assert payload["backend_stats"]["breakpoint_lines"] == payload["line_count"]
    assert payload["messages"]
    assert any(
        event == "stopped"
        and body.get("reason") == "breakpoint"
        and body.get("allThreadsStopped") is True
        for event, body in payload["messages"]
    )
    assert payload["stats_delta"]["slow_path_attempts"] >= 1
    assert payload["stats_delta"]["slow_path_activations"] >= 1
    assert payload["stats_delta"]["scoped_trace_installs"] >= 1


def test_eval_frame_backend_non_breakpointed_function_stays_on_fast_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import json
        from unittest.mock import MagicMock

        from dapper._frame_eval import CYTHON_AVAILABLE
        from dapper._frame_eval import types as frame_types
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.frame_eval_main import frame_eval_manager
        from dapper._frame_eval.frame_eval_main import shutdown_frame_eval
        from dapper.core.debugger_bdb import DebuggerBDB

        messages = []


        def send_message(event, **body):
            messages.append([event, body])


        def diff_stats(before, after):
            keys = (
                "slow_path_attempts",
                "slow_path_activations",
                "scoped_trace_installs",
                "return_events",
                "exception_events",
            )
            return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


        def sample_function():
            alpha = 3
            beta = 4
            gamma = alpha * beta
            return gamma


        if not CYTHON_AVAILABLE:
            print(json.dumps({"skipped": "cython unavailable"}, sort_keys=True))
            raise SystemExit(0)

        setup_ok = False
        integrated = False
        result = None
        runtime_status = None
        backend_stats = None
        stats_delta = None

        try:
            setup_ok = frame_eval_manager.setup_frame_eval(
                {"enabled": True, "backend": "EVAL_FRAME"}
            )
            backend = frame_eval_manager.active_backend
            runtime_status = frame_eval_manager.get_debug_info()["runtime_status"]

            if runtime_status.backend_type != "EvalFrameBackend":
                print(
                    json.dumps(
                        {
                            "backend_type": runtime_status.backend_type,
                            "skipped": f"eval-frame backend unavailable in this runtime (selected {runtime_status.backend_type})",
                        },
                        sort_keys=True,
                    )
                )
                raise SystemExit(0)

            debugger = DebuggerBDB(send_message=send_message)
            debugger.reset()
            debugger.process_commands = MagicMock()

            backend.update_breakpoints(sample_function.__code__.co_filename, set())

            stats_before = frame_types.get_frame_eval_stats()
            integrated = integrate_with_backend(backend, debugger)
            result = sample_function()
            stats_after = frame_types.get_frame_eval_stats()

            runtime_status = frame_eval_manager.get_debug_info()["runtime_status"]
            backend_stats = backend.get_statistics()
            stats_delta = diff_stats(stats_before, stats_after)

            print(
                json.dumps(
                    {
                        "backend_stats": backend_stats,
                        "backend_type": runtime_status.backend_type,
                        "hook_installed": runtime_status.hook_installed,
                        "integrated": integrated,
                        "messages": messages,
                        "result": result,
                        "setup_ok": setup_ok,
                        "stats_delta": stats_delta,
                    },
                    sort_keys=True,
                )
            )
        finally:
            shutdown_frame_eval()
        """
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr or result.stdout

    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert stdout_lines, result.stderr

    payload = json.loads(stdout_lines[-1])
    _skip_if_unavailable(payload)

    assert payload["setup_ok"] is True
    assert payload["integrated"] is True
    assert payload["backend_type"] == "EvalFrameBackend"
    assert payload["hook_installed"] is True
    assert payload["result"] == 12
    assert payload["backend_stats"]["installed"] is True
    assert payload["backend_stats"]["breakpoint_files"] == 1
    assert payload["backend_stats"]["breakpoint_lines"] == 0
    assert payload["messages"] == []
    assert payload["stats_delta"]["slow_path_attempts"] == 0
    assert payload["stats_delta"]["slow_path_activations"] == 0
    assert payload["stats_delta"]["scoped_trace_installs"] == 0
    assert payload["stats_delta"]["return_events"] == 0
    assert payload["stats_delta"]["exception_events"] == 0
