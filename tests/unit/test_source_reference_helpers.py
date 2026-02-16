from __future__ import annotations

import io
from pathlib import Path

import pytest

import dapper.shared.debug_shared as ds


class MockWFile(io.BytesIO):
    """Mock file for IPC writes."""

    def flush(self):
        pass


@pytest.fixture(autouse=True)
def _setup_ipc_for_tests():
    """Enable IPC on an explicit session so background paths stay isolated."""
    session = ds.DebugSession()
    session.ipc_enabled = True
    session.ipc_wfile = MockWFile()
    session.ipc_rfile = io.StringIO("")  # Empty reader to cause immediate exit
    with ds.use_session(session):
        yield session


def test_source_reference_round_trip(tmp_path):
    state = ds.get_active_session()
    p = tmp_path / "sample.py"
    p.write_text("print('hi')\n", encoding="utf-8")

    ref1 = state.get_or_create_source_ref(str(p), name="Sample")
    ref2 = state.get_or_create_source_ref(str(p), name="Ignored")  # should reuse
    assert ref1 == ref2

    meta = state.get_source_meta(ref1)
    assert meta is not None
    assert meta["path"] == str(p)
    # name stored (no crash on attempt)
    assert "name" in meta

    content_by_ref = state.get_source_content_by_ref(ref1)
    content_by_path = state.get_source_content_by_path(str(p))
    assert content_by_ref == content_by_path == "print('hi')\n"


def test_get_source_content_missing():
    state = ds.get_active_session()
    missing = state.get_source_content_by_path(str(Path("does_not_exist_file_xyz.py")))
    assert missing is None


def test_source_provider_register_unregister_and_exception_isolation():
    state = ds.get_active_session()
    calls: list[tuple[str, str]] = []

    def failing_provider(path_or_uri: str) -> str | None:
        calls.append(("fail", path_or_uri))
        msg = "expected test failure"
        raise RuntimeError(msg)

    def resolving_provider(path_or_uri: str) -> str | None:
        calls.append(("resolve", path_or_uri))
        if path_or_uri == "vscode-remote://workspace/main.py":
            return "provider-content"
        return None

    first_id = state.register_source_provider(failing_provider)
    second_id = state.register_source_provider(resolving_provider)

    content = state.get_source_content_by_path("vscode-remote://workspace/main.py")
    assert content == "provider-content"
    assert calls == [
        ("fail", "vscode-remote://workspace/main.py"),
        ("resolve", "vscode-remote://workspace/main.py"),
    ]

    assert state.unregister_source_provider(first_id) is True
    assert state.unregister_source_provider(first_id) is False
    assert state.unregister_source_provider(second_id) is True


def test_file_uri_normalizes_to_local_disk_path(tmp_path):
    state = ds.get_active_session()
    sample = tmp_path / "uri_sample.py"
    sample.write_text("print('from-uri')\n", encoding="utf-8")

    content = state.get_source_content_by_path(sample.as_uri())
    assert content == "print('from-uri')\n"


def test_non_file_uri_passed_to_provider_without_disk_fallback():
    state = ds.get_active_session()
    seen: list[str] = []

    def provider(path_or_uri: str) -> str | None:
        seen.append(path_or_uri)
        if path_or_uri == "git:/module.py":
            return "git-content"
        return None

    provider_id = state.register_source_provider(provider)
    try:
        assert state.get_source_content_by_path("git:/module.py") == "git-content"
        assert state.get_source_content_by_path("git:/missing.py") is None
    finally:
        state.unregister_source_provider(provider_id)

    assert seen == ["git:/module.py", "git:/missing.py"]
