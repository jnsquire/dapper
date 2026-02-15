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
    """Enable IPC with mock file so any background threads don't fail."""
    orig_enabled = ds.state.ipc_enabled
    orig_wfile = ds.state.ipc_wfile
    orig_rfile = ds.state.ipc_rfile

    # Start from a clean session state for deterministic behaviour
    ds.SessionState.reset()

    ds.state.ipc_enabled = True
    ds.state.ipc_wfile = MockWFile()
    ds.state.ipc_rfile = io.StringIO("")  # Empty reader to cause immediate exit
    yield
    # Restore prior environment to avoid surprising other tests
    ds.state.ipc_enabled = orig_enabled
    ds.state.ipc_wfile = orig_wfile
    ds.state.ipc_rfile = orig_rfile


def test_source_reference_round_trip(tmp_path):
    state = ds.state
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
    state = ds.state
    missing = state.get_source_content_by_path(str(Path("does_not_exist_file_xyz.py")))
    assert missing is None
