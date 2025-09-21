import asyncio
import sys
from pathlib import Path

import pytest

# Add the parent directory to PATH so that the dapper package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def event_loop():
    """Provide a fresh event loop for each test and ensure it is closed.

    Many sync tests still call asyncio.get_event_loop(); setting a loop here
    provides compatibility while keeping teardown deterministic across OSes.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        yield loop
    finally:
        try:
            if not loop.is_closed():
                # Cancel all pending tasks bound to this loop
                try:
                    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                # Shutdown async generators and default executor threads
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                try:
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
                # Finally close the loop
                try:
                    loop.close()
                except Exception:
                    pass
        finally:
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
