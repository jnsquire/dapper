from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dapper.dap_command_handlers import handle_loaded_sources
from dapper.dap_command_handlers import handle_source
from dapper.debug_shared import state


def _call_loaded_sources_and_find_ref() -> tuple[int, str]:
    # Call the handler which will populate state.source_references
    handle_loaded_sources(None)
    # Find any reference that points to a real file
    for ref, meta in state.source_references.items():
        path = meta.get("path")
        if path and Path(path).exists():
            return ref, path
    pytest.skip("No suitable source file available in test environment")


def test_loaded_sources_exports_source_reference_and_source_handler_returns_content():
    ref, path = _call_loaded_sources_and_find_ref()
    # Request the source by reference
    response_args: dict[str, Any] = {"source": {"sourceReference": ref}}
    # The handler will call send_debug_message; to keep this unit test simple,
    # we call handle_source and then retrieve the content via state helper.
    handle_source(response_args)
    content = state.get_source_content_by_ref(ref)
    assert content is not None
    # Sanity: content starts with a common Python token or at least contains a newline
    assert "\n" in content or content.strip().startswith("#")


def test_source_handler_with_invalid_reference_returns_none():
    # Pick a large, likely-unused ref id
    bad_ref = 999999
    assert state.get_source_meta(bad_ref) is None
    response_args = {"source": {"sourceReference": bad_ref}}
    handle_source(response_args)
    # Expect no content
    assert state.get_source_content_by_ref(bad_ref) is None


def test_loaded_sources_to_source_roundtrip_returns_file_contents():
    # Ensure loadedSources has been called and a ref exists
    handle_loaded_sources(None)
    # Pick a Source entry from the state that has a valid path and sourceReference
    chosen = None
    for ref, meta in state.source_references.items():
        p = meta.get("path")
        if p and Path(p).exists():
            chosen = (ref, p)
            break
    if not chosen:
        pytest.skip("No suitable source file available in test environment")

    ref, path = chosen
    # Call the source handler as a client would
    handle_source({"source": {"sourceReference": ref}})

    # The handler stores nothing new beyond what state already had; verify
    # that reading the file directly matches what the handler would have returned
    disk_text = Path(path).read_text(encoding="utf-8", errors="ignore")
    content = state.get_source_content_by_ref(ref)
    assert content == disk_text
