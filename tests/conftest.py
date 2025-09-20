import asyncio
import sys
from pathlib import Path

import pytest

# Add the parent directory to PATH so that the dapper package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Provide a fresh event loop for each test and ensure it is closed. This
# avoids relying on plugin behavior and guarantees deterministic cleanup of
# platform-specific resources (for example, the ProactorEventLoop's
# internal socketpair on Windows).


@pytest.fixture(autouse=True)
def event_loop():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        yield loop
    finally:
        try:
            if not loop.is_closed():
                loop.close()
        finally:
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
