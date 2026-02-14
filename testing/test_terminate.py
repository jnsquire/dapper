"""
Test script to verify the terminate request functionality.
"""

import asyncio
import json
import logging
from pathlib import Path
import socket
import subprocess
import sys
import traceback

logger = logging.getLogger(__name__)


class TerminateTest:
    MAX_CONNECTION_ATTEMPTS = 4

    def __init__(self):
        self.adapter_process = None
        self.client_socket = None
        self.port = 4711

    async def start_adapter(self):
        """Start the debug adapter in a subprocess."""
        cmd = [sys.executable, "-m", "dapper", "--tcp", str(self.port)]
        self.adapter_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        # Give the adapter time to start
        await asyncio.sleep(1)
        logger.info(f"\u2705 Started debug adapter on port {self.port}")

    async def connect_to_adapter(self):
        """Connect to the debug adapter."""
        for attempt in range(5):
            try:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.client_socket.connect(("localhost", self.port))
                logger.info("\u2705 Connected to debug adapter")
                return
            except ConnectionRefusedError:
                if attempt < self.MAX_CONNECTION_ATTEMPTS:
                    logger.info(f"Connection attempt {attempt + 1} failed, retrying...")
                    await asyncio.sleep(1)
                else:
                    raise

    def send_request(self, command, arguments=None):
        """Send a DAP request and return the response."""
        seq = 1
        request = {"seq": seq, "type": "request", "command": command}
        if arguments:
            request["arguments"] = arguments

        message = json.dumps(request)
        content_length = len(message.encode("utf-8"))

        full_message = f"Content-Length: {content_length}\r\n\r\n{message}"
        self.client_socket.send(full_message.encode("utf-8"))

        # Read response
        response_data = b""
        while True:
            chunk = self.client_socket.recv(1024)
            if not chunk:
                break
            response_data += chunk
            if b"\r\n\r\n" in response_data:
                break

        # Parse response
        headers, body = response_data.split(b"\r\n\r\n", 1)
        content_length = int(headers.split(b"Content-Length: ")[1].split(b"\r\n")[0])

        while len(body) < content_length:
            chunk = self.client_socket.recv(content_length - len(body))
            body += chunk

        return json.loads(body.decode("utf-8"))

    async def test_terminate_functionality(self):
        """Test the terminate request functionality."""
        logger.info("\n\ud83e\uddea Testing terminate functionality...")

        # Initialize the adapter
        response = self.send_request(
            "initialize",
            {
                "clientID": "test-client",
                "clientName": "Terminate Test",
                "adapterID": "dapper",
            },
        )

        if response.get("success"):
            logger.info("\u2705 Initialize request successful")
        else:
            logger.info(f"\u274c Initialize failed: {response}")
            return False

        # Launch a simple program
        response = self.send_request(
            "launch",
            {
                "program": str(
                    Path(__file__).resolve().parent.parent
                    / "examples"
                    / "sample_programs"
                    / "simple_app.py"
                ),
                "console": "none",
                "noDebug": False,
            },
        )

        if response.get("success"):
            logger.info("\u2705 Launch request successful")
        else:
            logger.info(f"\u274c Launch failed: {response}")
            return False

        # Give the program a moment to start
        await asyncio.sleep(0.5)

        # Send terminate request
        response = self.send_request("terminate")

        if response.get("success"):
            logger.info("\u2705 Terminate request successful")
            logger.info(f"   Response: {response}")
            return True
        logger.info(f"\u274c Terminate failed: {response}")
        return False

    async def cleanup(self):
        """Clean up resources."""
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass

        if self.adapter_process:
            try:
                self.adapter_process.terminate()
                self.adapter_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.adapter_process.kill()
            except Exception:
                pass
        logger.info("\u2705 Cleanup completed")


async def main():
    """Main test function."""
    test = TerminateTest()

    try:
        logger.info("=== Terminate Request Test ===")
        await test.start_adapter()
        await test.connect_to_adapter()
        success = await test.test_terminate_functionality()

        if success:
            logger.info("\n\ud83c\udf89 Terminate test PASSED!")
            return 0
        logger.info("\n\u274c Terminate test FAILED!")

    except Exception as e:
        logger.info("\n\ud83d\udca5 Test failed with exception: %s", e)
        traceback.print_exc()
        return 1
    else:
        return 1
    finally:
        await test.cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
