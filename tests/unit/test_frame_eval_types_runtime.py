from __future__ import annotations

import pytest

from dapper._frame_eval import types as frame_types


class _DummyCode:
    co_filename = "dummy_file.py"


class _DummyFrame:
    pass


def test_get_thread_info_returns_runtime_object() -> None:
    thread_info = frame_types.get_thread_info()

    assert thread_info is not Ellipsis
    assert hasattr(thread_info, "inside_frame_eval")
    assert hasattr(thread_info, "is_pydevd_thread")


def test_mark_unmark_and_skip_all_flags() -> None:
    frame_types.clear_thread_local_info()

    frame_types.mark_thread_as_pydevd()
    assert frame_types.get_thread_info().is_pydevd_thread is True

    frame_types.unmark_thread_as_pydevd()
    assert frame_types.get_thread_info().is_pydevd_thread is False

    frame_types.set_thread_skip_all(True)
    assert frame_types.get_thread_info().skip_all_frames is True

    frame_types.set_thread_skip_all(False)
    assert frame_types.get_thread_info().skip_all_frames is False


def test_clear_thread_local_info_resets_instance() -> None:
    before = frame_types.get_thread_info()
    frame_types.clear_thread_local_info()
    after = frame_types.get_thread_info()

    assert before is not after


def test_get_func_code_info_is_runtime_callable() -> None:
    info = frame_types.get_func_code_info(_DummyFrame(), _DummyCode())

    assert info is not Ellipsis
    assert hasattr(info, "breakpoint_found")
    assert hasattr(info, "update_breakpoint_info")


def test_get_frame_eval_stats_returns_mapping() -> None:
    stats = frame_types.get_frame_eval_stats()

    assert isinstance(stats, dict)
    assert "is_active" in stats or "active" in stats


def test_frame_eval_active_toggles_in_fallback() -> None:
    stats = frame_types.get_frame_eval_stats()
    if "is_active" not in stats:
        pytest.skip("Fallback-only assertion; Cython stats schema does not expose 'is_active'.")

    frame_types.stop_frame_eval()
    assert frame_types.get_frame_eval_stats()["is_active"] is False

    frame_types.frame_eval_func()
    assert frame_types.get_frame_eval_stats()["is_active"] is True

    frame_types.stop_frame_eval()
    assert frame_types.get_frame_eval_stats()["is_active"] is False
