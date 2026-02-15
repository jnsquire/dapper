from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from dapper.shared import debug_shared
from dapper.shared.source_handlers import handle_loaded_sources
from dapper.shared.source_handlers import handle_source


class MockWFile(io.BytesIO):
    """Mock file for IPC writes."""

    def flush(self):
        pass


@pytest.fixture(autouse=True)
def setup_ipc_for_tests():
    """Enable IPC with mock file for tests."""
    session = debug_shared.DebugSession()
    session.ipc_enabled = True
    session.ipc_wfile = MockWFile()
    with debug_shared.use_session(session):
        yield session


def _call_loaded_sources_and_find_ref(session) -> tuple[int, str]:
    # Call the handler which will populate session.source_references
    handle_loaded_sources(session, lambda *_args, **_kwargs: True)
    # Find any reference that points to a real file
    for ref, meta in session.source_references.items():
        path = meta.get("path")
        if path and Path(path).exists():
            return ref, path
    pytest.skip("No suitable source file available in test environment")


def test_loaded_sources_exports_source_reference_and_source_handler_returns_content(
    setup_ipc_for_tests,
):
    session = setup_ipc_for_tests
    ref, _path = _call_loaded_sources_and_find_ref(session)
    # Request the source by reference
    response_args: dict[str, Any] = {"source": {"sourceReference": ref}}
    # The handler will call send_debug_message; to keep this unit test simple,
    # we call handle_source and then retrieve the content via session helper.
    handle_source(response_args, session, lambda *_args, **_kwargs: True)
    content = session.get_source_content_by_ref(ref)
    assert content is not None
    # Sanity: content starts with a common Python token or at least contains a newline
    assert "\n" in content or content.strip().startswith("#")


def test_source_handler_with_invalid_reference_returns_none(setup_ipc_for_tests):
    session = setup_ipc_for_tests
    # Pick a large, likely-unused ref id
    bad_ref = 999999
    assert session.get_source_meta(bad_ref) is None
    response_args = {"source": {"sourceReference": bad_ref}}
    handle_source(response_args, session, lambda *_args, **_kwargs: True)
    # Expect no content
    assert session.get_source_content_by_ref(bad_ref) is None


def test_loaded_sources_to_source_roundtrip_returns_file_contents(setup_ipc_for_tests):
    session = setup_ipc_for_tests
    # Ensure loadedSources has been called and a ref exists
    handle_loaded_sources(session, lambda *_args, **_kwargs: True)
    # Pick a Source entry from the state that has a valid path and sourceReference
    chosen = None
    for ref, meta in session.source_references.items():
        p = meta.get("path")
        if p and Path(p).exists():
            chosen = (ref, p)
            break
    if not chosen:
        pytest.skip("No suitable source file available in test environment")

    ref, path = chosen
    # Call the source handler as a client would
    handle_source({"source": {"sourceReference": ref}}, session, lambda *_args, **_kwargs: True)

    # The handler stores nothing new beyond what session already had; verify
    # that reading the file directly matches what the handler would have returned
    disk_text = Path(path).read_text(encoding="utf-8", errors="ignore")
    content = session.get_source_content_by_ref(ref)
    assert content == disk_text
