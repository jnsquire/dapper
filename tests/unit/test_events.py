from dapper.utils.events import EventEmitter


def test_add_and_emit_listener():
    e = EventEmitter()
    calls = []

    def listener(a, b=0):
        calls.append((a, b))

    e.add_listener(listener)
    e.emit(1, b=2)
    assert calls == [(1, 2)]


def test_remove_listener():
    e = EventEmitter()
    calls = []

    def listener(x):
        calls.append(x)

    e.add_listener(listener)
    e.remove_listener(listener)
    e.emit(5)
    assert calls == []


def test_listener_removed_during_emit():
    e = EventEmitter()
    calls = []

    def listener_a():
        calls.append("a")
        # remove b while iterating
        e.remove_listener(listener_b)

    def listener_b():
        calls.append("b")

    e.add_listener(listener_a)
    e.add_listener(listener_b)
    e.emit()
    # Removal during emit does not stop the current iteration; both listeners run
    assert calls == ["a", "b"]

    # Subsequent emits should no longer call listener_b
    calls.clear()
    e.emit()
    assert calls == ["a"]


def test_listener_exception_is_logged(monkeypatch):
    e = EventEmitter()

    def bad_listener():
        msg = "boom"
        raise RuntimeError(msg)

    called = {"logged": False}

    def fake_exception(*_args, **_kwargs):
        called["logged"] = True

    monkeypatch.setattr("dapper.utils.events.logger.exception", fake_exception)
    e.add_listener(bad_listener)
    # Should not raise despite listener exception
    e.emit()
    assert called["logged"]


def test_add_same_listener_twice_and_remove_one():
    e = EventEmitter()
    calls = []

    def listener():
        calls.append(1)

    e.add_listener(listener)
    e.add_listener(listener)
    e.emit()
    assert calls == [1, 1]

    # Removing removes only one occurrence
    e.remove_listener(listener)
    calls.clear()
    e.emit()
    assert calls == [1]


def test_add_listener_during_emit_affects_next_emit():
    e = EventEmitter()
    calls = []

    def listener_b():
        calls.append("b")

    def adder():
        calls.append("a")
        # add listener_b while iterating
        e.add_listener(listener_b)

    e.add_listener(adder)
    e.emit()
    # listener_b shouldn't be called during the same emit
    assert calls == ["a"]

    # On next emit both adder and listener_b run
    e.emit()
    assert calls == ["a", "a", "b"]


def test_exception_in_listener_stops_following_and_logs(monkeypatch):
    e = EventEmitter()
    calls = []

    def bad():
        msg = "boom"
        raise RuntimeError(msg)

    def good():
        calls.append("ok")

    logged = {"ok": False}

    def fake_exception(*_args, **_kwargs):
        logged["ok"] = True

    monkeypatch.setattr("dapper.utils.events.logger.exception", fake_exception)
    e.add_listener(bad)
    e.add_listener(good)
    e.emit()
    # Good listener should still be called despite bad raising
    assert calls == ["ok"]
    assert logged["ok"]


def test_recursive_emit():
    e = EventEmitter()
    calls = []

    def a():
        calls.append("a")
        # recurse until we have 3 calls
        if len(calls) < 3:
            e.emit()

    e.add_listener(a)
    e.emit()
    assert calls == ["a", "a", "a"]
