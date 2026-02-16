from __future__ import annotations

import io
import logging
import struct

from dapper.ipc.ipc_binary import MAGIC
from dapper.ipc.ipc_binary import VERSION
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.reader_helpers import read_binary_stream


def test_read_binary_stream_short_header_stops(caplog):
    caplog.set_level(logging.ERROR)
    # stream shorter than a full header
    s = io.BytesIO(b"ABC")
    called: list[str] = []

    read_binary_stream(s, called.append)

    assert called == []
    assert any("short header" in rec.getMessage() for rec in caplog.records)


def test_read_binary_stream_partial_payload_stops(caplog):
    caplog.set_level(logging.ERROR)
    # Build a valid header claiming 10-byte payload but only supply 5 bytes
    length = 10
    header = MAGIC + bytes([VERSION, 1]) + struct.pack(">I", length)
    payload = b"ABCDE"
    s = io.BytesIO(header + payload)

    called: list[str] = []
    read_binary_stream(s, called.append)

    assert called == []
    assert any("short payload read" in rec.getMessage() for rec in caplog.records)


def test_read_binary_stream_success_calls_handler():
    payload = b"hello world"
    frame = pack_frame(1, payload)
    buf = io.BytesIO(frame)

    called: list[str] = []

    read_binary_stream(buf, called.append)

    assert called == [payload.decode("utf-8")]
