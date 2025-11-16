#!/usr/bin/env python3
"""
Test script to verify loadedSources functionality.
"""

import asyncio
import logging
from pathlib import Path

import pytest

from dapper.connections.tcp import TCPServerConnection
from dapper.server import PyDebugger

# Add the dapper module to the path

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
        # Test the get_loaded_sources method directly
        loaded_sources = await debugger.get_loaded_sources()

        # Get module names from loaded sources
        found_modules = {s.get("name") for s in loaded_sources if s.get("name")}

        # Verify this test file is included
        test_file_name = Path(__file__).name
        assert test_file_name in found_modules, (
            f"Test file {test_file_name} is missing from loaded sources"
        )

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
