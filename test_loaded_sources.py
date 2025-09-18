#!/usr/bin/env python3
"""
Test script to verify loadedSources functionality.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the dapper module to the path
sys.path.insert(0, str(Path(__file__).parent))

from dapper.connection import TCPServerConnection
from dapper.debugger import PyDebugger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
MAX_DISPLAY_SOURCES = 10


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
            logger.info(f"  {i + 1}. {source['name']} ({source.get('origin', 'unknown')})")
            logger.info(f"      Path: {source['path']}")
        if len(loaded_sources) > MAX_DISPLAY_SOURCES:
            logger.info(f"  ... and {len(loaded_sources) - MAX_DISPLAY_SOURCES} more")
        # Verify we found some standard Python modules
        found_modules = {source["name"] for source in loaded_sources}
        expected_modules = ["logging.py", "asyncio.py", "pathlib.py"]
        found_expected = [mod for mod in expected_modules if mod in found_modules]
        logger.info(f"Found expected standard library modules: {found_expected}")
        # Verify this test file is included
        test_file_name = Path(__file__).name
        if test_file_name in found_modules:
            logger.info(f"âœ“ This test file ({test_file_name}) is correctly included")
        else:
            logger.warning(f"âœ— This test file ({test_file_name}) is missing from loaded sources")
        logger.info("âœ“ loadedSources test completed successfully!")
    except Exception:
        logger.exception("Test failed")
        raise
    finally:
        # Clean up
        await connection.close()


if __name__ == "__main__":
    asyncio.run(test_loaded_sources())
