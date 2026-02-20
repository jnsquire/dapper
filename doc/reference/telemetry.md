# Frame-eval telemetry (reference)

This reference documents the small telemetry surface exposed by the frame-eval subsystem.

## Purpose

Telemetry records structured reason codes and a short recent-event list for diagnostics, debugging, and CI assertions. It's intended for observability and debugging (not for high-volume analytics).

## Public API

- `get_frame_eval_telemetry()`
  - Returns a snapshot with two keys: `reason_counts` (map of reason-code → count) and `recent_events` (list of timestamped events).

- `reset_frame_eval_telemetry()`
  - Clears all collected telemetry.

- `telemetry` (singleton instance)
  - Record a reason code and optional context via kwargs (generally used internally; available for tests and advanced diagnostics).
  - Exposes methods like `record_auto_integration_failed(**kwargs)`, `record_bytecode_injection_failed(**kwargs)`, etc.

## Example

```python
from dapper._frame_eval.telemetry import (
    get_frame_eval_telemetry,
    reset_frame_eval_telemetry,
    telemetry,
)

# Inspect current telemetry
snap = get_frame_eval_telemetry()
print(snap.reason_counts)        # FrameEvalReasonCounts(bytecode_injection_failed=2, ...)
print(len(snap.recent_events))  # up to the configured recent-events window

# Clear telemetry (useful in tests)
reset_frame_eval_telemetry()

# Test helper: ensure a reason was recorded
assert get_frame_eval_telemetry().reason_counts.bytecode_injection_failed > 0
```

## Where to look in code

- `dapper._frame_eval.telemetry` — collector + enum + helpers
- `dapper._frame_eval.modify_bytecode` and `dapper._frame_eval.bytecode_safety` — emit bytecode-related reason codes
- `dapper._frame_eval.selective_tracer` and `dapper._frame_eval.condition_evaluator` — selective-tracing diagnostics

---

See also: the user guide section `Frame Evaluation — Telemetry & selective tracing` in the Getting Started docs.