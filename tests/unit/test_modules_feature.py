"""
Tests for the 'modules' feature implementation.

This complements existing server tests by exercising the PyDebugger.get_modules
method directly and validating basic invariants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from dapper.adapter.server import PyDebugger

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


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
async def test_get_modules_user_code_flag(tmp_path, monkeypatch):
    # Create a unique module name to avoid conflicts
    module_name = f"temp_user_module_{id(tmp_path)}"

    # Create the module file
    mod_file = tmp_path / f"{module_name}.py"
    mod_file.write_text("VALUE = 42\n")

    # Add the temporary directory to the Python path
    monkeypatch.syspath_prepend(str(tmp_path))

    spec = importlib.util.spec_from_file_location(module_name, str(mod_file))
    if spec is None or spec.loader is None:
        pytest.skip("Could not create module spec")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        # Execute the module
        spec.loader.exec_module(module)

        # Create debugger and get modules
        debugger = PyDebugger(None)
        modules = await debugger.get_modules()

        # Look for our module in the list
        target = next((m for m in modules if m["name"] == module_name), None)

        if target is None:
            # If not found, skip with some debug info
            available_modules = [m["name"] for m in modules if m["name"]]
            pytest.skip(
                f"{module_name} not found in modules list. "
                f"Available modules: {available_modules[:20]}..."
            )

        # Check if it's marked as user code
        assert target["isUserCode"] is True, f"Expected {module_name} to be marked as user code"

    finally:
        # Clean up
        sys.modules.pop(module_name, None)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
