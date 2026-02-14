"""
Example: Run the DAP adapter on a background thread while your app runs on
 the main thread (in-process debugging mode).

This script starts the Debug Adapter Protocol (DAP) server in a daemon
thread using the TCP connection. Your application code keeps running on the
main thread. You can attach a DAP client (like VS Code) to control execution.

How to use (VS Code):
- Open this repo in VS Code.
- Use the launch config in examples/inprocess_launch.json as a template.
- Or start the adapter here (it binds an ephemeral port) and connect your DAP
  client to that port via "debugServer".

Behavior:
- Starts AdapterThread with TCP and port=0 (ephemeral). Prints the bound port.
- Runs a simple demo workload on the main thread.
- Gracefully stops the adapter thread on exit.
"""

from __future__ import annotations

from contextlib import suppress
import logging
import signal
import sys
import threading
import time

from dapper.adapter.adapter_thread import AdapterThread

logger = logging.getLogger(__name__)
MAIN_LOOP_MAX_ITER = 50


def _configure_logging() -> None:
    # Console logging only for the example
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


PORT_WAIT_TIMEOUT = 5.0


def main() -> None:
    _configure_logging()
    logger.info("Starting adapter in background thread (TCP, ephemeral port)...")

    adapter = AdapterThread(connection_type="tcp", host="127.0.0.1", port=0)

    # Set up a threading event to capture the port when it's assigned
    port_event = threading.Event()
    assigned_port: int | None = None

    def on_port(port: int) -> None:
        nonlocal assigned_port
        assigned_port = port
        port_event.set()

    adapter.on_port_assigned.add_listener(on_port)
    adapter.start()

    # Wait for the port to be assigned
    if port_event.wait(timeout=PORT_WAIT_TIMEOUT):
        logger.info("Adapter listening on tcp://127.0.0.1:%s", assigned_port)
        logger.info("Use a DAP client configured with debugServer=%s to attach.", assigned_port)
    else:
        logger.warning(
            "Could not determine adapter port within %.1fs. It may still be starting.",
            PORT_WAIT_TIMEOUT,
        )

    stop = False

    def _handle_signal(_signum, _frame):
        nonlocal stop
        stop = True

    # Handle Ctrl+C gracefully
    with suppress(Exception):
        signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Running demo workload on main thread. Press Ctrl+C to stop...")

    counter = 0
    try:
        while not stop and counter < MAIN_LOOP_MAX_ITER:
            # Simulate your application work here
            counter += 1
            if counter % 10 == 0:
                logger.info("Main loop heartbeat: counter=%s", counter)
            time.sleep(0.1)
    finally:
        logger.info("Stopping adapter thread...")
        adapter.stop(join=True)
        logger.info("Adapter stopped. Goodbye.")


if __name__ == "__main__":
    main()
