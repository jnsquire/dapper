#!/usr/bin/env python3
"""
Test script for verifying the Dapper debug adapter setup.

This script helps verify that the debug adapter can be launched and
that example programs can be run and debugged.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DebugAdapterTester:
    """Test harness for the debug adapter."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.adapter_process: subprocess.Popen[bytes] | None = None
        self.test_results: dict[str, Any] = {}

    def test_adapter_launch_tcp(self, port: int = 4711) -> bool:
        """Test launching the debug adapter with TCP connection."""
        logger.info(f"Testing debug adapter launch on TCP port {port}...")

        try:
            # Launch the debug adapter
            cmd = [
                sys.executable,
                "-m",
                "dapper.adapter",
                "--port",
                str(port),
                "--log-level",
                "INFO",
            ]

            self.adapter_process = subprocess.Popen(
                cmd,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Give it time to start
            time.sleep(2)

            # Check if process is still running
            if self.adapter_process.poll() is not None:
                stdout, stderr = self.adapter_process.communicate()
                logger.info("❌ Adapter process terminated early")
                logger.info(f"STDOUT: {stdout}")
                logger.info(f"STDERR: {stderr}")
                return False

            # Try to connect to the port
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex(("localhost", port))
                sock.close()

                if result == 0:
                    logger.info(f"✅ Debug adapter is listening on port {port}")
                    return True
                logger.info(f"❌ Cannot connect to port {port}")
                return False

            except Exception as e:
                logger.info(f"❌ Error testing connection: {e}")
                return False

        except Exception as e:
            logger.info(f"❌ Error launching adapter: {e}")
            return False

    def test_example_programs(self) -> dict[str, bool]:
        """Test that example programs can run without errors."""
        logger.info("Testing example programs...")

        results = {}
        example_programs = [
            "examples/sample_programs/simple_app.py",
            "examples/sample_programs/advanced_app.py",
        ]

        for program in example_programs:
            program_path = self.project_root / program
            if not program_path.exists():
                logger.info(f"❌ Example program not found: {program}")
                results[program] = False
                continue

            try:
                logger.info(f"  Testing {program}...")
                result = subprocess.run(
                    [sys.executable, str(program_path)],
                    check=False,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    logger.info(f"  ✅ {program} ran successfully")
                    results[program] = True
                else:
                    logger.info(f"  ❌ {program} failed with return code {result.returncode}")
                    logger.info(f"  STDERR: {result.stderr}")
                    results[program] = False

            except subprocess.TimeoutExpired:
                logger.info(f"  ❌ {program} timed out")
                results[program] = False
            except Exception as e:
                logger.info(f"  ❌ Error running {program}: {e}")
                results[program] = False

        return results

    def test_vscode_configuration(self) -> bool:
        """Test that VS Code configuration files are valid."""
        logger.info("Testing VS Code configuration...")

        vscode_dir = self.project_root / ".vscode"
        if not vscode_dir.exists():
            logger.info("❌ .vscode directory not found")
            return False

        # Test launch.json
        launch_json = vscode_dir / "launch.json"
        if not launch_json.exists():
            logger.info("❌ launch.json not found")
            return False

        try:
            with Path(launch_json).open(encoding="utf-8") as f:
                launch_config = json.load(f)

            if "configurations" not in launch_config:
                logger.info("❌ launch.json missing configurations")
                return False

            configs = launch_config["configurations"]
            if not configs:
                logger.info("❌ No launch configurations found")
                return False

            logger.info(f"✅ Found {len(configs)} launch configurations:")
            for config in configs:
                name = config.get("name", "Unknown")
                config_type = config.get("type", "Unknown")
                logger.info(f"  - {name} ({config_type})")

            return True

        except json.JSONDecodeError as e:
            logger.info(f"❌ Invalid JSON in launch.json: {e}")
            return False
        except Exception as e:
            logger.info(f"❌ Error reading launch.json: {e}")
            return False

    def cleanup(self) -> None:
        """Clean up any running processes."""
        if self.adapter_process:
            logger.info("Cleaning up adapter process...")
            self.adapter_process.terminate()
            try:
                self.adapter_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.adapter_process.kill()
                self.adapter_process.wait()

    def run_all_tests(self) -> dict[str, Any]:
        """Run all tests and return results."""
        logger.info("=== Dapper Debug Adapter Test Suite ===")

        try:
            # Test 1: VS Code configuration
            vscode_test = self.test_vscode_configuration()
            self.test_results["vscode_config"] = vscode_test

            # Test 2: Example programs
            example_tests = self.test_example_programs()
            self.test_results["example_programs"] = example_tests

            # Test 3: Debug adapter launch
            adapter_test = self.test_adapter_launch_tcp()
            self.test_results["adapter_launch"] = adapter_test

            # Summary
            logger.info("\n=== Test Summary ===")
            logger.info(f"VS Code configuration: {'✅' if vscode_test else '❌'}")
            logger.info(f"Adapter launch: {'✅' if adapter_test else '❌'}")

            logger.info("Example programs:")
            for program, success in example_tests.items():
                logger.info(f"  {program}: {'✅' if success else '❌'}")

            # Overall success
            overall_success = vscode_test and adapter_test and all(example_tests.values())

            logger.info(
                f"\nOverall result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}"
            )
            self.test_results["overall_success"] = overall_success

            return self.test_results

        finally:
            self.cleanup()


def main():
    """Main function to run the test suite."""
    # Find project root - go up one level from testing directory
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    # Look for dapper module to confirm we're in the right place
    if not (project_root / "dapper" / "__init__.py").exists():
        logger.info(
            "❌ Cannot find dapper module. Make sure you're running from the project root."
        )
        logger.info(f"Script path: {script_path}")
        logger.info(f"Detected project root: {project_root}")
        sys.exit(1)

    logger.info(f"Project root: {project_root}")

    # Run tests
    tester = DebugAdapterTester(project_root)
    results = tester.run_all_tests()

    # Exit with appropriate code
    if results.get("overall_success", False):
        logger.info("\n🎉 All tests passed! Your debug adapter setup is ready.")
        sys.exit(0)
    else:
        logger.info("\n💥 Some tests failed. Please check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
