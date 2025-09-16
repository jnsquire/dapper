"""
Main Debug Adapter entry point
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from dapper.connection import NamedPipeServerConnection
from dapper.connection import TCPServerConnection
from dapper.server import DebugAdapterServer

logger = logging.getLogger(__name__)


async def start_server(
    connection_type: str,
    host: str = "localhost",
    port: int = 4711,
    pipe_name: str | None = None,
) -> None:
    """
    Start the debug adapter server with the specified connection type
    """
    logger.info("Starting debug adapter with %s connection", connection_type)

    connection = None
    if connection_type == "tcp":
        connection = TCPServerConnection(host=host, port=port)
    elif connection_type == "pipe":
        if pipe_name is None:
            pipe_name = "dapper_debug_pipe"
        connection = NamedPipeServerConnection(pipe_name=pipe_name)
    else:
        logger.error("Unknown connection type: %s", connection_type)
        return

    server = DebugAdapterServer(connection)
    await server.start()


def main() -> None:
    """
    Main entry point for the debug adapter
    """
    # Configure logging only when the adapter is executed as a script.
    # Configure console logging only. Avoid creating a FileHandler here so
    # tests that patch the module logger don't cause the test runner to open
    # files during import/execution which can lead to ResourceWarning/unraisable
    # exceptions in some test environments.
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    parser = argparse.ArgumentParser(description="Debug adapter for Python")

    connection_group = parser.add_mutually_exclusive_group(required=True)
    connection_group.add_argument("--port", type=int, help="TCP port to listen on")
    connection_group.add_argument("--pipe", type=str, help="Named pipe to use for communication")

    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind to (default: localhost)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    if args.port:
        connection_type = "tcp"
        port = args.port
        pipe_name = None
    else:
        connection_type = "pipe"
        port = None
        pipe_name = args.pipe

    try:
        if port is not None:
            asyncio.run(
                start_server(
                    connection_type,
                    args.host,
                    port,
                    pipe_name,
                )
            )
        else:
            # Use default port when none was specified
            # pass explicit None for the port so argument order is consistent
            asyncio.run(start_server(connection_type, host=args.host, pipe_name=pipe_name))
    except KeyboardInterrupt:
        logger.info("Debug adapter stopped by user")
    except Exception:
        # Log the error at error level and include exception info. Using
        # logger.error(..., exc_info=True) avoids calling logger.exception()
        # which some tests mock differently; tests expect logger.error to be
        # called when a general exception occurs.
        logger.exception("Error in debug adapter")
        sys.exit(1)


if __name__ == "__main__":
    main()
