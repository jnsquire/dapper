"""Small helpers for reading DBGP messages from pipes and sockets.

Centralises the blocking read loops used by IPCContext so testable
helpers can be reused and the high-level context class is smaller.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import Callable

from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import read_exact
from dapper.ipc.ipc_binary import unpack_header

logger = logging.getLogger(__name__)


def read_text_stream(rfile: Any, handle_debug_message: Callable[[str], None]) -> None:
    """Read text DBGP lines from a file-like object until EOF.

    Lines should be prefixed with "DBGP:" and will be passed (trimmed)
    to handle_debug_message.
    """
    while True:
        line = rfile.readline()
        if not line:
            break
        if isinstance(line, str) and line.startswith("DBGP:"):
            try:
                handle_debug_message(line[5:].strip())
            except Exception:
                logger.exception("handle_debug_message failed")


def read_binary_stream(rfile: Any, handle_debug_message: Callable[[str], None]) -> None:
    """Read binary framed DBGP messages from a file-like object until EOF.

    Uses IPC binary framing helpers to extract the payload and calls the
    handler for payloads whose frame 'kind' indicates a debug message.
    """
    while True:
        header = read_exact(rfile, HEADER_SIZE)
        # EOF before any bytes -> normal stop
        if not header:
            break
        # If we received fewer bytes than a full header, treat as EOF/partial and stop
        if len(header) < HEADER_SIZE:
            logger.error("short header read from binary stream: %d bytes", len(header))
            break
        try:
            kind, length = unpack_header(header)
        except Exception:
            # Bad header; stop reading to avoid mis-parsing following bytes
            logger.exception("invalid binary frame header")
            break
        payload = read_exact(rfile, length)
        # If payload is shorter than expected, treat as EOF/partial and stop
        if not payload:
            break
        if len(payload) < length:
            logger.error(
                "short payload read from binary stream: expected %d got %d", length, len(payload)
            )
            break
        if kind == 1:
            try:
                handle_debug_message(payload.decode("utf-8"))
            except Exception:
                logger.exception("handle_debug_message failed")


def read_pipe_text(conn: Any, handle_debug_message: Callable[[str], None]) -> None:
    """Read text messages from a multiprocessing pipe-like connection."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if isinstance(msg, str) and msg.startswith("DBGP:"):
            try:
                handle_debug_message(msg[5:].strip())
            except Exception:
                logger.exception("handle_debug_message failed")


def read_pipe_binary(conn: Any, handle_debug_message: Callable[[str], None]) -> None:
    """Read raw bytes from a pipe connection and unpack DBGP frames.

    The pipe-level recv_bytes may return whole frames or empty bytes representing EOF.
    """
    while True:
        try:
            data = conn.recv_bytes()
        except (EOFError, OSError):
            break
        if not data:
            break
        try:
            kind, length = unpack_header(data[:HEADER_SIZE])
        except Exception:
            break
        payload = data[HEADER_SIZE : HEADER_SIZE + length]
        if kind == 1:
            try:
                handle_debug_message(payload.decode("utf-8"))
            except Exception:
                logger.exception("handle_debug_message failed")
