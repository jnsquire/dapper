import asyncio
import sys
from pathlib import Path

import pytest

# Add the parent directory to PATH so that the dapper package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Fixture for asyncio loop
@pytest.fixture
def event_loop():
    """Use the current running event loop for each test."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # If no loop is running, pytest-asyncio will create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        created_new = True
    else:
        created_new = False

    yield loop

    # Only close if we created it
    if created_new and not loop.is_closed():
        loop.close()
