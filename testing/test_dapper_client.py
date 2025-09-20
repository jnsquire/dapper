#!/usr/bin/env python3
"""
Debug Adapter Protocol client for testing the Dapper debug adapter.

This script acts as a DAP client (like VS Code would) to connect to your
debug adapter and send commands to debug a Python program.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DAPClient:
    """Debug Adapter Protocol client for testing."""

    def __init__(self, host: str = "localhost", port: int = 4711):
        self.host = host
        self.port = port
        self.socket: socket.socket | None = None
        self.seq = 1

    def connect(self) -> bool:
        """Connect to the debug adapter."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            logger.info(f"✅ Connected to debug adapter at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.info(f"❌ Failed to connect to debug adapter: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the debug adapter."""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
            logger.info("🔌 Disconnected from debug adapter")

    def send_request(
        self, command: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a DAP request and return the response."""
        if not self.socket:
            msg = "Not connected to debug adapter"
            raise RuntimeError(msg)

        request = {"seq": self.seq, "type": "request", "command": command}

        if arguments:
            request["arguments"] = arguments

        self.seq += 1

        # Send the request
        request_json = json.dumps(request)
        message = f"Content-Length: {len(request_json)}\r\n\r\n{request_json}"

        logger.info(f"📤 Sending: {command}")
        logger.info(f"   {request_json}")

        self.socket.send(message.encode("utf-8"))

        # Read the response
        response = self._read_message()
        logger.info(f"📥 Received: {response.get('command', 'response')}")
        logger.info(f"   {json.dumps(response, indent=2)}")

        return response

    def _read_message(self) -> dict[str, Any]:
        """Read a DAP message from the socket."""
        if not self.socket:
            msg = "Not connected"
            raise RuntimeError(msg)

        # Read Content-Length header
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            chunk = self.socket.recv(1)
            if not chunk:
                msg = "Connection closed"
                raise RuntimeError(msg)
            header += chunk

        # Parse Content-Length
        header_str = header.decode("utf-8")
        content_length = 0
        for line in header_str.split("\r\n"):
            if line.startswith("Content-Length:"):
                content_length = int(line.split(":")[1].strip())
                break

        if content_length == 0:
            msg = "No Content-Length header found"
            raise RuntimeError(msg)

        # Read the message body
        body = b""
        while len(body) < content_length:
            remaining = content_length - len(body)
            chunk = self.socket.recv(remaining)
            if not chunk:
                msg = "Connection closed"
                raise RuntimeError(msg)
            body += chunk

        # Parse JSON
        return json.loads(body.decode("utf-8"))

    def debug_program(self, program_path: str) -> bool:
        """Debug a Python program using the DAP."""
        try:
            logger.info(f"🐛 Starting debug session for: {program_path}")

            # 1. Initialize
            logger.info("\n📋 Step 1: Initialize")
            init_response = self.send_request(
                "initialize",
                {
                    "clientID": "dapper-test-client",
                    "clientName": "Dapper Test Client",
                    "adapterID": "dapper",
                    "pathFormat": "path",
                    "linesStartAt1": True,
                    "columnsStartAt1": True,
                    "supportsVariableType": True,
                    "supportsVariablePaging": False,
                    "supportsRunInTerminalRequest": False,
                },
            )

            if not init_response.get("success", False):
                logger.info("❌ Initialize failed")
                return False

            # 2. Launch
            logger.info("\n🚀 Step 2: Launch")
            launch_response = self.send_request(
                "launch",
                {
                    "program": program_path,
                    "console": "internalConsole",
                    "stopOnEntry": False,
                    "python": sys.executable,
                },
            )

            if not launch_response.get("success", False):
                logger.info("❌ Launch failed")
                return False

            # 3. Set breakpoints
            logger.info("\n🔴 Step 3: Set breakpoints")
            self.send_request(
                "setBreakpoints",
                {
                    "source": {"path": program_path},
                    "breakpoints": [
                        {"line": 70},  # In main() function
                        {"line": 85},  # After stats calculation
                    ],
                },
            )

            # 4. Configure done
            logger.info("\n⚙️ Step 4: Configuration done")
            self.send_request("configurationDone")

            # 5. Wait for events and continue execution
            logger.info("\n▶️ Step 5: Continue execution")
            self.send_request("continue", {"threadId": 1})

            logger.info("\n✅ Debug session initiated successfully!")
            logger.info("💡 The program should now be running under the debugger")
            logger.info("💡 Check the debug adapter logs for detailed communication")

            return True

        except Exception as e:
            logger.info(f"❌ Error during debug session: {e}")
            return False


def test_debug_adapter_connection(host: str, port: int) -> bool:
    """Test basic connection to the debug adapter.

    This function is called from `main()` with explicit arguments; tests
    should not rely on default values for host/port.
    """
    logger.info(f"🔍 Testing connection to debug adapter at {host}:{port}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            logger.info("✅ Debug adapter is running and accepting connections")
            return True
        logger.info("❌ Cannot connect to debug adapter")
        logger.info("💡 Make sure to start the debug adapter first:")
        logger.info("   python -m dapper.adapter --port 4711")
        return False

    except Exception as e:
        logger.info(f"❌ Connection test failed: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Test client for Dapper debug adapter")
    parser.add_argument("--program", required=True, help="Python program to debug")
    parser.add_argument("--host", default="localhost", help="Debug adapter host")
    parser.add_argument("--port", type=int, default=4711, help="Debug adapter port")
    parser.add_argument("--test-only", action="store_true", help="Only test connection")

    args = parser.parse_args()

    logger.info("=== Dapper Debug Adapter Client Test ===")

    # Test connection first
    if not test_debug_adapter_connection(args.host, args.port):
        sys.exit(1)

    if args.test_only:
        logger.info("✅ Connection test successful!")
        return

    # Verify program exists
    program_path = Path(args.program).resolve()
    if not program_path.exists():
        logger.info(f"❌ Program not found: {program_path}")
        sys.exit(1)

    # Create DAP client and debug the program
    client = DAPClient(args.host, args.port)

    try:
        if client.connect():
            success = client.debug_program(str(program_path))
            if success:
                logger.info("\n🎉 Debug session completed successfully!")
            else:
                logger.info("\n💥 Debug session failed!")
                sys.exit(1)
        else:
            sys.exit(1)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
