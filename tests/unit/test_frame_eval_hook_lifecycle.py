"""Tests for the low-level eval-frame hook lifecycle controller."""

from dapper._frame_eval import get_eval_frame_hook_status
from dapper._frame_eval import install_eval_frame_hook
from dapper._frame_eval import types as frame_types
from dapper._frame_eval import uninstall_eval_frame_hook


def test_low_level_hook_install_uninstall_is_idempotent() -> None:
    uninstall_eval_frame_hook()

    assert install_eval_frame_hook() is True
    assert install_eval_frame_hook() is True

    status = get_eval_frame_hook_status()
    assert status["available"] is True
    assert status["installed"] is True

    assert uninstall_eval_frame_hook() is True
    assert uninstall_eval_frame_hook() is True

    status = get_eval_frame_hook_status()
    assert status["available"] is True
    assert status["installed"] is False


def test_types_surface_exposes_hook_status() -> None:
    uninstall_eval_frame_hook()
    assert frame_types.install_eval_frame_hook() is True

    stats = frame_types.get_frame_eval_stats()
    hook_status = frame_types.get_eval_frame_hook_status()

    assert stats["hook_available"] is True
    assert stats["hook_installed"] is True
    assert hook_status["installed"] is True

    assert frame_types.uninstall_eval_frame_hook() is True
