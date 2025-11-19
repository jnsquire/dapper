from __future__ import annotations

import struct
from typing import BinaryIO

MAGIC = b"DP"  # Dapper Protocol
VERSION = 1


def pack_frame(kind: int, payload: bytes) -> bytes:
    """Pack a binary frame: MAGIC(2) + VER(1) + KIND(1) + LEN(4 BE) + PAYLOAD.

    kind: 1 = event (DBGP), 2 = command (DBGCMD)
    """
    header = MAGIC + bytes([VERSION, kind]) + struct.pack(">I", len(payload))
    return header + payload


HEADER_SIZE = 8


def unpack_header(buf: bytes) -> tuple[int, int]:
    """Return (kind, length) from a validated header; raise ValueError on bad magic/version."""
    if len(buf) != HEADER_SIZE:
        msg = "invalid header size"
        raise ValueError(msg)
    if buf[:2] != MAGIC:
        msg = "bad magic"
        raise ValueError(msg)
    ver = buf[2]
    if ver != VERSION:
        msg = "unsupported version"
        raise ValueError(msg)
    kind = buf[3]
    length = struct.unpack(">I", buf[4:8])[0]
    return kind, int(length)


def read_exact(stream: BinaryIO, n: int) -> bytes:
    """Read exactly n bytes from a buffered stream; return b"" if EOF before any byte read."""
    chunks = bytearray()
    while len(chunks) < n:
        chunk = stream.read(n - len(chunks))
        if not chunk:
            # EOF
            return b"" if not chunks else bytes(chunks)
        chunks.extend(chunk)
    return bytes(chunks)
