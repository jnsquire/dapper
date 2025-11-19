"""
Demo: Restart request against Dapper server

This script starts a Debug Adapter server on an ephemeral TCP port,
connects a tiny DAP client to it, launches in in-process mode, and
then issues a 'restart' request. It prints the key responses/events.

Run:
    uv run python examples/demo_restart.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from dapper.adapter.server import DebugAdapterServer
from dapper.ipc.connections.tcp import TCPServerConnection


def _encode_message(msg: dict[str, Any]) -> bytes:
    body = json.dumps(msg).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    return header + body


async def _read_message(
    reader: asyncio.StreamReader,
) -> dict[str, Any] | None:
    # Read headers
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            return None
        s = line.decode("utf-8").strip()
        if not s:
            break
        key, value = s.split(":", 1)
        headers[key.strip()] = value.strip()

    length = int(headers.get("Content-Length", "0"))
    if length <= 0:
        return None
    data = await reader.readexactly(length)
    return json.loads(data.decode("utf-8"))


async def main() -> None:
    # 1) Start server on ephemeral TCP port
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(conn, loop)

    server_task = asyncio.create_task(server.start())

    # Wait briefly for the TCP server to bind and expose the port
    # (accept() updates conn.port before waiting for the first client)
    await asyncio.sleep(0.05)
    port = conn.port

    # 2) Connect a simple DAP client
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    seq = 1

    def send(msg: dict[str, Any]) -> None:
        nonlocal seq
        msg.setdefault("seq", seq)
        seq += 1
        writer.write(_encode_message(msg))

    async def recv_until(count: int, timeout: float = 2.0) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for _ in range(count):
            m = await asyncio.wait_for(_read_message(reader), timeout=timeout)
            if m is None:
                break
            out.append(m)
        return out

    # 3) initialize
    send(
        {
            "type": "request",
            "command": "initialize",
            "arguments": {"adapterID": "dapper-demo"},
        }
    )
    msgs = await recv_until(2)  # response + initialized event
    for m in msgs:
        print("<-", m.get("type"), m.get("event") or m.get("command"))

    # 4) launch (in-process) with a sample program path
    sample_prog = Path(__file__).resolve()
    send(
        {
            "type": "request",
            "command": "launch",
            "arguments": {
                "program": str(sample_prog),
                "inProcess": True,
            },
        }
    )
    msgs = await recv_until(1)  # launch response
    for m in msgs:
        print("<-", m.get("type"), m.get("event") or m.get("command"))

    # 5) restart
    send(
        {
            "type": "request",
            "command": "restart",
        }
    )
    # Expect: restart response, then terminated event with restart=true
    msgs = await recv_until(2)
    for m in msgs:
        print(
            "<-",
            m.get("type"),
            m.get("event") or m.get("command"),
            m.get("body"),
        )

    # Close client and wait for server to wind down
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(server_task, timeout=1.0)


if __name__ == "__main__":
    import contextlib

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
