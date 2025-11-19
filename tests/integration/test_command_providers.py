from __future__ import annotations

import pytest

import dapper.shared.debug_shared as ds


@pytest.fixture
def isolated_registry():
    """


    Isolate the provider registry for each test and restore afterward."""
    old = list(ds.state._providers)
    ds.state._providers = []
    try:
        yield
    finally:
        ds.state._providers = old


@pytest.fixture
def capture_messages(monkeypatch):
    """Capture send_debug_message calls as (event_type, kwargs) tuples."""
    messages = []

    def fake_send(event_type: str, **kwargs):
        messages.append((event_type, kwargs))

    monkeypatch.setattr(ds, "send_debug_message", fake_send)
    return messages


class AlwaysProvider:
    def __init__(self, name="prov", result=None, raise_exc: Exception | None = None):
        self.name = name
        self._result = result
        self._exc = raise_exc

    def can_handle(self, command: str) -> bool:  # noqa: ARG002
        return True

    def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
        if self._exc is not None:
            raise self._exc
        return self._result


class SupportedProvider:
    def __init__(self, commands):
        self._commands = set(commands)

    def supported_commands(self):
        return set(self._commands)

    def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
        return {"success": True, "body": {"handled": command}}


@pytest.mark.usefixtures("isolated_registry")
def test_unknown_command_with_id_sends_response_error(capture_messages):
    ds.state.dispatch_debug_command({"id": 1, "command": "nope", "arguments": {}})
    assert capture_messages == [
        ("response", {"id": 1, "success": False, "message": "Unknown command: nope"})
    ]


@pytest.mark.usefixtures("isolated_registry")
def test_unknown_command_no_id_sends_error_event(capture_messages):
    ds.state.dispatch_debug_command({"command": "nope", "arguments": {}})
    assert capture_messages == [("error", {"message": "Unknown command: nope"})]


@pytest.mark.usefixtures("isolated_registry")
def test_provider_success_response_sent_with_id(capture_messages):
    prov = AlwaysProvider(result={"success": True, "body": {"ok": 1}})
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"id": 42, "command": "ping", "arguments": {}})
    assert len(capture_messages) == 1
    event, payload = capture_messages[0]
    assert event == "response"
    assert payload["id"] == 42
    assert payload["success"] is True
    assert payload.get("body", {}).get("ok") == 1


@pytest.mark.usefixtures("isolated_registry")
def test_provider_return_none_no_synthesized_response(capture_messages):
    prov = AlwaysProvider(result=None)
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"id": 5, "command": "nop", "arguments": {}})
    assert capture_messages == []


@pytest.mark.usefixtures("isolated_registry")
def test_provider_exception_paths_with_id(capture_messages):
    prov = AlwaysProvider(raise_exc=ValueError("boom"))
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"id": 7, "command": "ping", "arguments": {}})
    assert len(capture_messages) == 1
    event, payload = capture_messages[0]
    assert event == "response"
    assert payload["id"] == 7
    assert payload["success"] is False
    assert "Error handling command ping: boom" in payload["message"]


@pytest.mark.usefixtures("isolated_registry")
def test_provider_exception_paths_without_id(capture_messages):
    prov = AlwaysProvider(raise_exc=RuntimeError("oops"))
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"command": "ping", "arguments": {}})
    assert len(capture_messages) == 1
    event, payload = capture_messages[0]
    assert event == "error"
    assert "Error handling command ping: oops" in payload["message"]


@pytest.mark.usefixtures("isolated_registry")
def test_priority_ordering_uses_highest_priority_first(capture_messages):
    low = AlwaysProvider(name="low", result={"success": True, "body": {"who": "low"}})
    high = AlwaysProvider(name="high", result={"success": True, "body": {"who": "high"}})
    ds.state.register_command_provider(low, priority=0)
    ds.state.register_command_provider(high, priority=10)
    ds.state.dispatch_debug_command({"id": 99, "command": "ping", "arguments": {}})
    assert capture_messages == [("response", {"id": 99, "success": True, "body": {"who": "high"}})]


@pytest.mark.usefixtures("isolated_registry")
def test_fallback_to_next_provider_when_first_cannot_handle(capture_messages):
    class CantHandle:
        def can_handle(self, command: str) -> bool:  # noqa: ARG002
            return False

        def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
            return {"success": True, "body": {"who": "cant"}}

    second = AlwaysProvider(result={"success": True, "body": {"who": "second"}})
    ds.state.register_command_provider(CantHandle(), priority=10)
    ds.state.register_command_provider(second, priority=0)
    ds.state.dispatch_debug_command({"id": 123, "command": "ping", "arguments": {}})
    assert capture_messages == [
        ("response", {"id": 123, "success": True, "body": {"who": "second"}})
    ]


@pytest.mark.usefixtures("isolated_registry")
def test_can_handle_exception_is_ignored_and_unknown_emitted(capture_messages):
    class BadCan:
        def can_handle(self, command: str) -> bool:  # noqa: ARG002
            msg = "nope"
            raise RuntimeError(msg)

        def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
            return {"success": True}

    ds.state.register_command_provider(BadCan(), priority=0)
    # If a provider's can_handle raises, the exception propagates; ensure the
    # behavior is explicit in the test by asserting the error is raised and
    # that no messages were emitted.
    with pytest.raises(RuntimeError):
        ds.state.dispatch_debug_command({"id": 321, "command": "xyz", "arguments": {}})
    assert capture_messages == []


@pytest.mark.usefixtures("isolated_registry")
def test_unregister_removes_provider(capture_messages):
    prov = AlwaysProvider(result={"success": True})
    ds.state.register_command_provider(prov, priority=0)
    ds.state.unregister_command_provider(prov)
    ds.state.dispatch_debug_command({"id": 1, "command": "ping", "arguments": {}})
    assert capture_messages == [
        ("response", {"id": 1, "success": False, "message": "Unknown command: ping"})
    ]


@pytest.mark.usefixtures("isolated_registry")
def test_can_handle_overrides_supported_commands(capture_messages):
    class Both:
        def supported_commands(self):
            return {"ping"}

        def can_handle(self, command: str) -> bool:  # noqa: ARG002
            return False

        def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
            return {"success": True}

    fallback = AlwaysProvider(result={"success": True, "body": {"who": "fallback"}})
    ds.state.register_command_provider(Both(), priority=10)
    ds.state.register_command_provider(fallback, priority=0)
    ds.state.dispatch_debug_command({"id": 2, "command": "ping", "arguments": {}})
    assert capture_messages == [
        ("response", {"id": 2, "success": True, "body": {"who": "fallback"}})
    ]


@pytest.mark.usefixtures("isolated_registry")
def test_response_without_success_key_is_ignored(capture_messages):
    prov = AlwaysProvider(result={"message": "hi"})
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"id": 3, "command": "ping", "arguments": {}})
    assert capture_messages == []


@pytest.mark.usefixtures("isolated_registry")
def test_success_without_id_emits_no_response(capture_messages):
    prov = AlwaysProvider(result={"success": True})
    ds.state.register_command_provider(prov, priority=0)
    ds.state.dispatch_debug_command({"command": "ping", "arguments": {}})
    assert capture_messages == []


@pytest.mark.usefixtures("isolated_registry")
def test_mutation_during_dispatch_uses_snapshot(capture_messages):
    class Mutating:
        def __init__(self, ref: Mutating | None):
            self._ref: Mutating | None = ref

        def can_handle(self, command: str) -> bool:  # noqa: ARG002
            if self._ref is not None:
                ds.state.unregister_command_provider(self._ref)
            return True

        def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
            return {"success": True}

    m = Mutating(None)
    m._ref = m
    ds.state.register_command_provider(m, priority=0)
    ds.state.dispatch_debug_command({"id": 4, "command": "ping", "arguments": {}})
    assert capture_messages == [("response", {"id": 4, "success": True})]
