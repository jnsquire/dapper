"""
Main Debug Adapter entry point
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from dapper.connections.pipe import NamedPipeServerConnection
from dapper.connections.tcp import TCPServerConnection
from dapper.server import DebugAdapterServer

if TYPE_CHECKING:
    from dapper.connections import ConnectionBase


logger = logging.getLogger(__name__)


async def create_connection(
    connection_type: str,
    host: str = "localhost",
    port: int | None = None,
    pipe_name: str | None = None,
) -> ConnectionBase | None:
    connection = None
    if connection_type == "tcp":
        connection = TCPServerConnection(host=host, port=port or 4711)
    elif connection_type == "pipe":
        if pipe_name is None:
            pipe_name = "dapper_debug_pipe"
        connection = NamedPipeServerConnection(pipe_name=pipe_name)
    else:
        logger.error("Unknown connection type: %s", connection_type)
        return None
    return connection


async def start_server(
    connection_type: str,
    host: str = "localhost",
    port: int | None = None,
    pipe_name: str | None = None,
) -> None:
    """
    Start the debug adapter server with the specified connection type
    """
    logger.info("Starting debug adapter with %s connection", connection_type)

    connection = await create_connection(
        connection_type,
        host=host,
        port=port,
        pipe_name=pipe_name,
    )

    if connection:
        server = DebugAdapterServer(connection)
        await server.start()


# Eventually this can just be logging.getLevelNamesMapping()
NAME_TO_LEVEL: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


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

    logging.getLogger().setLevel(NAME_TO_LEVEL.get(args.log_level, logging.INFO))

    if args.port:
        connection_type = "tcp"
        port = args.port
        pipe_name = None
    else:
        connection_type = "pipe"
        port = None
        pipe_name = args.pipe

    try:
        asyncio.run(
            start_server(
                connection_type,
                args.host,
                port,
                pipe_name,
            )
        )
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
