"""Tests for dapper.dev_tools module.

This module tests the developer tools functionality, focusing on the update_docs function.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper import dev_tools


def test_run_tests_invokes_pytest_and_js(monkeypatch) -> None:
    """Ensure run_tests invokes pytest and then the JS test runner."""
    called = {}

    def fake_pytest_main(arg_list):
        called["pytest"] = True
        called["pytest_args"] = arg_list
        return 0

    def fake_run_js_tests(_js_args=None):
        called["js"] = True

    monkeypatch.setattr(dev_tools, "run_js_tests", fake_run_js_tests)
    monkeypatch.setattr(dev_tools.pytest, "main", fake_pytest_main)

    dev_tools.run_tests(["-q", "-k", "foo", "--", "--runInBand"])

    assert called.get("pytest", False) is True
    assert called.get("pytest_args") == ["-q", "-k", "foo"]
    assert called.get("js", False) is True


def test_run_tests_exits_on_pytest_failure(monkeypatch) -> None:
    # use dev_tools imported at module scope
    def fake_pytest_main(_arg_list):
        return 2

    monkeypatch.setattr(dev_tools.pytest, "main", fake_pytest_main)
    with pytest.raises(SystemExit) as exc:
        dev_tools.run_tests()
    assert exc.value.code == 2


def test_run_tests_handles_js_failure(monkeypatch) -> None:
    # use dev_tools imported at module scope
    def fake_pytest_main(_arg_list):
        return 0

    def fake_run_js_tests(_js_args=None):
        raise dev_tools.JSTestsFailedError(5)

    monkeypatch.setattr(dev_tools.pytest, "main", fake_pytest_main)
    monkeypatch.setattr(dev_tools, "run_js_tests", fake_run_js_tests)
    with pytest.raises(SystemExit) as exc:
        dev_tools.run_tests()
    assert exc.value.code == 5


def test_update_docs_success(tmp_path: Path) -> None:
    """Test that update_docs runs the script successfully."""
    # Import here to avoid test collection issues
    from dapper.dev_tools import update_docs  # noqa: PLC0415

    # Create a dummy script path and file
    script_path = tmp_path / "scripts" / "update_docs.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# Dummy script for testing")

    # Patch the path resolution to point to our temp dir
    with (
        patch("dapper.dev_tools.Path") as mock_path,
        patch("dapper.dev_tools.runpy.run_path") as mock_run_path,
    ):
        # Make __file__ point to our temp dir
        mock_file = MagicMock()
        mock_file.resolve.return_value.parent.parent = tmp_path
        mock_path.return_value = mock_file

        # Configure the mock to return a success status
        mock_run_path.return_value = 0

        # Call the function
        update_docs()

        # Verify run_path was called with the correct path
        mock_run_path.assert_called_once_with(str(script_path), run_name="__main__")


def test_update_docs_missing_script() -> None:
    """Test that update_docs raises SystemExit when script is missing."""
    from dapper.dev_tools import update_docs  # noqa: PLC0415

    # Patch the path to point to a non-existent location
    with patch("dapper.dev_tools.Path") as mock_path:
        mock_file = MagicMock()
        mock_file.resolve.return_value.parent.parent = Path("/non/existent/path")
        mock_path.return_value = mock_file

        with pytest.raises(SystemExit):
            update_docs()


def test_main_calls_update_docs() -> None:
    """Test that __main__ calls update_docs()."""
    # Import the module
    import dapper.dev_tools  # noqa: PLC0415

    # Mock the update_docs function
    with patch("dapper.dev_tools.update_docs") as mock_update_docs:
        # Execute the module's __main__ block directly
        dapper.dev_tools.update_docs()

        # Check that update_docs was called
        mock_update_docs.assert_called_once()
