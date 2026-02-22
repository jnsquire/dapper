"""Unit tests for frame-eval telemetry collection and reason codes."""

from __future__ import annotations

import json

from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry
from dapper._frame_eval.telemetry import telemetry


def test_telemetry_records_reason_code_counts() -> None:
    """Reason code records should increment counts."""
    reset_frame_eval_telemetry()

    telemetry.record_bytecode_injection_failed()
    telemetry.record_bytecode_injection_failed()

    snap = get_frame_eval_telemetry()

    assert snap.reason_counts.bytecode_injection_failed == 2


def test_telemetry_records_context_events() -> None:
    """Recorded events should include context payloads."""
    reset_frame_eval_telemetry()

    telemetry.record_integration_bdb_failed(
        debugger="mock",
        phase="integrate",
    )

    snap = get_frame_eval_telemetry()

    assert len(snap.recent_events) == 1
    event = snap.recent_events[0]
    assert event.reason_code == "INTEGRATION_BDB_FAILED"
    assert event.context["debugger"] == "mock"
    assert event.context["phase"] == "integrate"


def test_telemetry_reset_clears_state() -> None:
    """Reset should clear both counts and recent events."""
    reset_frame_eval_telemetry()
    telemetry.record_auto_integration_failed()

    reset_frame_eval_telemetry()
    snap = get_frame_eval_telemetry()

    assert snap.reason_counts.as_dict() == {}
    assert snap.recent_events == []


def test_snapshot_as_json() -> None:
    """Snapshot should serialize cleanly to JSON."""
    reset_frame_eval_telemetry()
    telemetry.record_auto_integration_failed(debug=True)

    snap = get_frame_eval_telemetry()
    j = snap.as_json()
    assert isinstance(j, str)

    obj = json.loads(j)
    assert "reason_counts" in obj
    assert "recent_events" in obj


def test_telemetry_records_hot_reload_metrics() -> None:
    """Hot-reload telemetry records both success and failure counters."""
    reset_frame_eval_telemetry()

    telemetry.record_hot_reload_succeeded(module="mod", duration_ms=4.2)
    telemetry.record_hot_reload_failed(module="mod", error_type="ValueError")

    snap = get_frame_eval_telemetry()
    assert snap.reason_counts.hot_reload_succeeded == 1
    assert snap.reason_counts.hot_reload_failed == 1

    assert len(snap.recent_events) == 2
    assert snap.recent_events[0].reason_code == "HOT_RELOAD_SUCCEEDED"
    assert snap.recent_events[1].reason_code == "HOT_RELOAD_FAILED"
