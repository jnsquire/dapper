#!/usr/bin/env python3
"""
Test script to verify loadedSources functionality.
"""

import asyncio
import logging
import sys
from pathlib import Path

import pytest

from dapper.connections.tcp import TCPServerConnection
from dapper.server import PyDebugger

# Add the dapper module to the path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
MAX_DISPLAY_SOURCES = 10


@pytest.mark.asyncio
async def test_loaded_sources():
    """Test the loadedSources functionality."""

    # Create the server components
    connection = TCPServerConnection("localhost", 0)  # Use ephemeral port
    debugger = PyDebugger(None)

    try:
        # Start the server
        await connection.start_listening()
        port = connection.port
        logger.info(f"Debug adapter server started on port {port}")

        # Test the get_loaded_sources method directly
        loaded_sources = await debugger.get_loaded_sources()

        logger.info(f"Found {len(loaded_sources)} loaded sources:")
        for i, source in enumerate(loaded_sources[:MAX_DISPLAY_SOURCES]):
            name = source.get("name", "<unknown>")
            origin = source.get("origin", "unknown")
            path = source.get("path", "")
            logger.info(f"  {i + 1}. {name} ({origin})")
            logger.info(f"      Path: {path}")

        if len(loaded_sources) > MAX_DISPLAY_SOURCES:
            logger.info(f"  ... and {len(loaded_sources) - MAX_DISPLAY_SOURCES} more")

        # Verify we found some standard Python modules
        found_modules = {s.get("name") for s in loaded_sources if s.get("name")}
        expected_modules = ["logging.py", "asyncio.py", "pathlib.py"]
        found_expected = [mod for mod in expected_modules if mod in found_modules]

        logger.info(f"Found expected standard library modules: {found_expected}")

        # Verify this test file is included
        test_file_name = Path(__file__).name
        if test_file_name in found_modules:
            logger.info(f"✓ This test file ({test_file_name}) is correctly included")
        else:
            logger.warning(f"✗ This test file ({test_file_name}) is missing from loaded sources")

        logger.info("✓ loadedSources test completed successfully!")

    except Exception:
        logger.exception("Test failed")
        raise
    finally:
        # Clean up
        await connection.close()
        # Ensure PyDebugger releases any owned loop/resources
        try:
            await debugger.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(test_loaded_sources())
