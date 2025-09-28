from __future__ import annotations

import io
import struct

import pytest

from dapper.ipc_binary import HEADER_SIZE
from dapper.ipc_binary import MAGIC
from dapper.ipc_binary import VERSION
from dapper.ipc_binary import pack_frame
from dapper.ipc_binary import read_exact
from dapper.ipc_binary import unpack_header


def test_unpack_header_invalid_size():
    with pytest.raises(ValueError, match="invalid header size"):
        unpack_header(b"short")


def test_unpack_header_bad_magic():
    # construct a header with wrong magic
    header = b"XX" + bytes([VERSION, 1]) + struct.pack(">I", 0)
    with pytest.raises(ValueError, match="bad magic"):
        unpack_header(header)


def test_unpack_header_unsupported_version():
    # construct a header with right magic but wrong version
    header = MAGIC + bytes([VERSION + 1, 1]) + struct.pack(">I", 0)
    with pytest.raises(ValueError, match="unsupported version"):
        unpack_header(header)


def test_read_exact_eof_before_anything_returns_empty():
    s = io.BytesIO(b"")
    assert read_exact(s, 5) == b""


def test_read_exact_partial_then_eof_returns_partial_bytes():
    # stream smaller than requested
    s = io.BytesIO(b"ABC")
    # request 5 bytes -> should return the 3 available bytes
    assert read_exact(s, 5) == b"ABC"


def test_read_exact_successful_read():
    payload = b"hello world"
    frame = pack_frame(1, payload)
    # stream contains header+payload; read only payload part using read_exact
    buf = io.BytesIO(frame)
    # skip header
    buf.read(HEADER_SIZE)
    got = read_exact(buf, len(payload))
    assert got == payload
