import inspect
import threading

from dapper._frame_eval.selective_tracer import SelectiveTraceDispatcher


def _sample_frame():
    return inspect.currentframe()


def test_selective_trace_dispatch_does_not_hold_lock_during_callback(monkeypatch) -> None:
    dispatcher = SelectiveTraceDispatcher()

    callback_entered = threading.Event()
    callback_can_exit = threading.Event()
    lock_acquired_while_callback_running = threading.Event()

    def trace_callback(_frame, _event, _arg):
        callback_entered.set()
        callback_can_exit.wait(timeout=1.0)

    dispatcher.set_debugger_trace_func(trace_callback)

    monkeypatch.setattr(
        dispatcher.analyzer,
        "should_trace_frame",
        lambda _frame: {
            "should_trace": True,
            "reason": "test",
            "breakpoint_lines": set(),
            "frame_info": {
                "filename": "test.py",
                "function": "test_fn",
                "lineno": 1,
                "is_module": False,
            },
        },
    )

    def try_update_trace_func() -> None:
        if callback_entered.wait(timeout=1.0):
            dispatcher.set_debugger_trace_func(trace_callback)
            lock_acquired_while_callback_running.set()

    updater_thread = threading.Thread(target=try_update_trace_func, daemon=True)
    updater_thread.start()

    dispatch_thread = threading.Thread(
        target=dispatcher.selective_trace_dispatch,
        args=(_sample_frame(), "line", None),
        daemon=True,
    )
    dispatch_thread.start()

    assert callback_entered.wait(timeout=1.0)
    assert lock_acquired_while_callback_running.wait(timeout=1.0)

    callback_can_exit.set()
    dispatch_thread.join(timeout=1.0)
    updater_thread.join(timeout=1.0)

    assert not dispatch_thread.is_alive()
    assert not updater_thread.is_alive()
