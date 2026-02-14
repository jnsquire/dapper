"""
Streamlined test runner for Dapper debug adapter.

This script provides a simple interface to test the debug adapter
in various modes without cluttering the main directory.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import subprocess
import sys
import time

# Set up logger for this module
logger = logging.getLogger(__name__)


def run_setup_tests() -> bool:
    """Run the automated setup verification tests."""
    logger.info("🧪 Running setup verification tests...")
    testing_dir = Path(__file__).parent
    setup_test = testing_dir / "test_debug_adapter_setup.py"

    try:
        result = subprocess.run(
            [sys.executable, str(setup_test)],
            check=False,
            cwd=testing_dir.parent,
        )
    except Exception:
        logger.exception("Error running setup tests")
        return False
    else:
        return result.returncode == 0


def start_debug_adapter(port: int = 4711) -> subprocess.Popen[bytes]:
    """Start the debug adapter in the background."""
    logger.info("🚀 Starting debug adapter on port %d...", port)

    cmd = [
        sys.executable,
        "-m",
        "dapper.adapter",
        "--port",
        str(port),
        "--log-level",
        "INFO",
    ]
    process = subprocess.Popen(cmd, cwd=Path(__file__).parent.parent)

    # Give it time to start
    time.sleep(2)

    if process.poll() is not None:
        msg = "Debug adapter failed to start"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("✅ Debug adapter running (PID: %d)", process.pid)
    return process


def test_connection(port: int) -> bool:
    """Test connection to the debug adapter."""
    logger.info("🔍 Testing connection to debug adapter on port %d...", port)
    testing_dir = Path(__file__).parent
    client_test = testing_dir / "test_dapper_client.py"

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(client_test),
                "--test-only",
                "--program",
                "examples/sample_programs/simple_app.py",
            ],
            check=False,
            cwd=testing_dir.parent,
        )
    except Exception:
        logger.exception("Error testing connection")
        return False
    else:
        return result.returncode == 0


def run_debug_session(program: str, port: int = 4711) -> bool:
    """Run a full debug session with the specified program."""
    logger.info("🐛 Running debug session for %s...", program)
    testing_dir = Path(__file__).parent
    client_test = testing_dir / "test_dapper_client.py"

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(client_test),
                "--program",
                program,
                "--port",
                str(port),
            ],
            check=False,
            cwd=testing_dir.parent,
        )
    except Exception:
        logger.exception("Error running debug session")
        return False
    else:
        return result.returncode == 0


def show_manual_instructions():
    """Show manual testing instructions."""
    logger.info("""
📋 Manual Testing Instructions
=============================

For VS Code testing:
1. Open Run and Debug panel (Ctrl+Shift+D)
2. Select "Launch Debug Adapter (TCP)"
3. Click the green play button
4. In another terminal/VS Code instance, use "Test Dapper Debug Adapter"

For command line testing:
1. Terminal 1: python -m dapper --port 4711
2. Terminal 2: python testing/test_dapper_client.py --program examples/sample_programs/simple_app.py

Available test programs:
- examples/sample_programs/simple_app.py (basic scenarios)
- examples/sample_programs/advanced_app.py (complex scenarios)
""")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Dapper debug adapter test runner",
    )
    parser.add_argument(
        "command",
        choices=["setup", "start", "connect", "debug", "manual", "full"],
        help="Test command to run",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4711,
        help="Debug adapter port",
    )
    parser.add_argument(
        "--program",
        default="examples/sample_programs/simple_app.py",
        help="Program to debug",
    )

    args = parser.parse_args()

    logger.info("=== Dapper Debug Adapter Test Runner ===")

    if args.command == "setup":
        # Run setup verification tests
        success = run_setup_tests()
        sys.exit(0 if success else 1)

    elif args.command == "start":
        # Start debug adapter and wait
        process = start_debug_adapter(args.port)
        if process:
            try:
                logger.info("Press Ctrl+C to stop the debug adapter...")
                process.wait()
            except KeyboardInterrupt:
                logger.info("\n🛑 Stopping debug adapter...")
                process.terminate()
                process.wait()

    elif args.command == "connect":
        # Test connection to running adapter
        success = test_connection(args.port)
        sys.exit(0 if success else 1)

    elif args.command == "debug":
        # Run debug session (requires running adapter)
        success = run_debug_session(args.program, args.port)
        sys.exit(0 if success else 1)

    elif args.command == "manual":
        # Show manual testing instructions
        show_manual_instructions()

    elif args.command == "full":
        # Full automated test: start adapter, test connection, run debug session
        logger.info("🎯 Running full automated test...")

        # Start adapter
        process = start_debug_adapter(args.port)
        if not process:
            sys.exit(1)

        try:
            # Test connection
            if not test_connection(args.port):
                logger.error("Connection test failed")
                sys.exit(1)

            # Run debug session
            if not run_debug_session(args.program, args.port):
                logger.error("Debug session failed")
                sys.exit(1)

            logger.info("🎉 All tests passed!")

        finally:
            logger.info("🛑 Stopping debug adapter...")
            process.terminate()
            process.wait()


if __name__ == "__main__":
    main()
