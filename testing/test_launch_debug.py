#!/usr/bin/env python3
"""
Simple test runner for debugging launch tests
"""

import asyncio
import sys
import traceback

# Add the project root to the path
from tests.test_debugger_launch import TestDebuggerLaunch


async def run_single_test():
    """Run a single test to check for hanging"""

    test_instance = TestDebuggerLaunch()
    await test_instance.asyncSetUp()

    try:
        await test_instance.test_launch_with_args()
    except Exception:
        traceback.print_exc()
        return False
    else:
        return True
    finally:
        await test_instance.asyncTearDown()


if __name__ == "__main__":
    result = asyncio.run(run_single_test())
    sys.exit(0 if result else 1)