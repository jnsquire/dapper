"""
Simple test script for the integrated debugging example.
This script verifies that the example can be imported and run.
"""

import logging
import subprocess
import sys
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)


def test_import():
    """Test that we can import the debugger components"""
    try:
        import_module("dapper.debug_launcher")
    except ImportError:
        logger.exception("Failed to import DebuggerBDB")
        return False
    else:
        logger.info("Successfully imported DebuggerBDB")
        return True


def test_example_execution():
    """Test that the example can be executed"""
    try:
        # Run the example with a timeout to prevent hanging
        example_dir = Path(__file__).resolve().parent
        example_path = example_dir / "integrated_debugging.py"
        result = subprocess.run(
            [
                sys.executable,
                str(example_path),
                "--no-debug",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.exception("Example timed out")
        return False
    except Exception:
        logger.exception("Failed to execute example")
        return False
    else:
        if result.returncode == 0:
            logger.info("Example executed successfully")
            return True
        logger.error("Example failed with return code %s", result.returncode)
        logger.error("stderr: %s", result.stderr)
        return False


def main():
    """Run all tests"""
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing Integrated Debugging Example")
    logger.info("%s", "=" * 40)

    tests = [
        ("Import Test", test_import),
        ("Execution Test", test_example_execution),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        logger.info("\n%s:", test_name)
        if test_func():
            passed += 1
        else:
            logger.error("  FAILED")

    logger.info("\n%s", "=" * 40)
    logger.info("Results: %s/%s tests passed", passed, total)

    if passed == total:
        logger.info("All tests passed")
        return 0
    logger.error("Some tests failed")
    return 1
