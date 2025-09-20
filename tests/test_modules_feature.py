"""Tests for the 'modules' feature implementation.

This complements existing server tests by exercising the PyDebugger.get_modules
method directly and validating basic invariants.
"""

from __future__ import annotations

import sys

import pytest

from dapper.server import PyDebugger


@pytest.mark.asyncio
async def test_get_modules_basic():
    debugger = PyDebugger(None)
    modules = await debugger.get_modules()
    # Should return a non-empty list
    assert isinstance(modules, list)
    assert modules, "Expected some modules to be returned"
    # Each module should have required keys
    for m in modules[:10]:  # sample first 10
        assert "id" in m
        assert "name" in m
        assert "isUserCode" in m
    # Expect core modules like 'sys' to be present
    names = {m["name"] for m in modules}
    assert "sys" in names


@pytest.mark.asyncio
async def test_get_modules_user_code_flag(tmp_path):
    # Dynamically create a temporary user module to ensure heuristic marks it as user code.
    mod_file = tmp_path / "temp_user_module.py"
    mod_file.write_text("VALUE = 42\n")
    sys.path.insert(0, str(tmp_path))
    try:
        __import__("temp_user_module")
        debugger = PyDebugger(None)
        modules = await debugger.get_modules()
        target = next((m for m in modules if m["name"] == "temp_user_module"), None)
        assert target is not None, "temp_user_module not found in modules list"
        # The heuristic should typically mark this as user code (not in stdlib / site-packages)
        assert target.get("isUserCode") is True
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
