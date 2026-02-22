from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from typing import cast
from unittest.mock import Mock

from dapper.adapter.server import PyDebugger


def _capture_frame():
    return inspect.currentframe()


def test_resolve_runtime_frame_prefers_inprocess_frame_map():
    dbg = PyDebugger(Mock())
    frame = _capture_frame()
    assert frame is not None

    frame_map = {123: frame}

    def _get_frame_by_id(frame_id: int):
        return frame_map.get(frame_id)

    def _get_current_frame():
        return None

    bdb = SimpleNamespace(
        thread_tracker=SimpleNamespace(frame_id_to_frame=frame_map),
        get_frame_by_id=_get_frame_by_id,
        get_current_frame=_get_current_frame,
    )
    cast("Any", dbg)._inproc_backend = SimpleNamespace(
        bridge=SimpleNamespace(debugger=SimpleNamespace(debugger=bdb)),
    )
    dbg.current_frame = None

    assert dbg.resolve_runtime_frame(123) is frame


def test_resolve_runtime_frame_falls_back_to_current_frame():
    dbg = PyDebugger(Mock())
    frame = _capture_frame()
    assert frame is not None

    def _get_frame_by_id(_frame_id: int):
        return None

    def _get_current_frame():
        return None

    bdb = SimpleNamespace(
        thread_tracker=SimpleNamespace(frame_id_to_frame={}),
        get_frame_by_id=_get_frame_by_id,
        get_current_frame=_get_current_frame,
    )
    cast("Any", dbg)._inproc_backend = SimpleNamespace(
        bridge=SimpleNamespace(debugger=SimpleNamespace(debugger=bdb)),
    )
    dbg.current_frame = frame

    assert dbg.resolve_runtime_frame(999) is frame


def test_iter_live_frames_deduplicates_current_frame():
    dbg = PyDebugger(Mock())
    frame_a = _capture_frame()
    frame_b = _capture_frame()
    assert frame_a is not None
    assert frame_b is not None

    frame_map = {1: frame_a, 2: frame_b}

    def _get_frame_by_id(frame_id: int):
        return frame_map.get(frame_id)

    def _get_current_frame():
        return frame_b

    bdb = SimpleNamespace(
        thread_tracker=SimpleNamespace(frame_id_to_frame=frame_map),
        get_frame_by_id=_get_frame_by_id,
        get_current_frame=_get_current_frame,
    )
    cast("Any", dbg)._inproc_backend = SimpleNamespace(
        bridge=SimpleNamespace(debugger=SimpleNamespace(debugger=bdb)),
    )

    frames = dbg.iter_live_frames()

    assert frame_a in frames
    assert frame_b in frames
    assert len(frames) == 2
