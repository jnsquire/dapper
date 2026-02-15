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
