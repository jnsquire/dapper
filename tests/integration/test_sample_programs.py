"""Smoke tests for the example programs in ``examples/sample_programs``.

These tests don't exercise the debugger itself; they simply verify that the
scripts can be executed without crashing.  Having a test ensures the examples
stay runnable when refactoring or moving files around.
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger(__name__)


def _run_example(script_name: str) -> None:
    # descend three levels to reach repository root, then point at the
    # examples/sample_programs directory.  previous version accidentally
    # looked in tests/examples which does not exist.
    example_dir = Path(__file__).resolve().parent.parent.parent / "examples" / "sample_programs"
    script_path = example_dir / script_name
    logger.info("running example %s", script_path)
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        logger.error("stdout:\n%s", result.stdout)
        logger.error("stderr:\n%s", result.stderr)
    assert result.returncode == 0, f"{script_name} failed with {result.returncode}"


def test_simple_app_runs() -> None:
    _run_example("simple_app.py")


def test_loop_example_runs() -> None:
    _run_example("loop_example.py")


def test_advanced_app_runs() -> None:
    _run_example("advanced_app.py")
