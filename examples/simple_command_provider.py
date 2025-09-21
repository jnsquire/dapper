"""
Minimal example of a session-aware DebugCommandProvider.

Run this file to see the provider in action printing responses dispatched by
SessionState. This demonstrates how to implement supported_commands/handle
and how to register the provider.
"""

from __future__ import annotations

import dapper.debug_shared as ds


class HelloProvider:
    """A simple provider that handles two commands: "hello" and "sum".

    Contract:
    - supported_commands(): iterable of command strings it can handle
    - handle(session, command, arguments, full_command) -> dict | None
      Return a dict with a "success" key to have the session synthesize a
      response using the incoming command id (if present). Return None if
      you already sent messages yourself.
    """

    def supported_commands(self):
        return {"hello", "sum"}

    def handle(self, session, command: str, arguments, full_command):  # noqa: ARG002
        if command == "hello":
            name = arguments.get("name", "world")
            return {"success": True, "body": {"greeting": f"Hello, {name}!"}}
        if command == "sum":
            nums = arguments.get("nums", [])
            try:
                total = sum(int(n) for n in nums)
            except Exception as exc:  # defensive: show error back to caller
                return {"success": False, "message": f"invalid numbers: {exc!s}"}
            return {"success": True, "body": {"sum": total}}
        # Not expected to reach here because supported_commands gates dispatch
        return {"success": False, "message": f"Unknown: {command}"}


def main() -> None:
    # Register the provider at a moderate priority
    ds.state.register_command_provider(HelloProvider(), priority=10)

    # For demo purposes, patch send_debug_message so we can see the synthesized
    # responses from dispatch on the console.
    def _print_send(event_type: str, **kwargs):
        print(f"{event_type}: {kwargs}")

    ds.send_debug_message = _print_send  # type: ignore[assignment]

    # Dispatch a few sample commands. When an "id" is provided, dispatch will
    # synthesize a response using the dict returned from handle().
    ds.state.dispatch_debug_command({"id": 1, "command": "hello", "arguments": {"name": "Ada"}})
    ds.state.dispatch_debug_command({"id": 2, "command": "sum", "arguments": {"nums": [1, 2, 3]}})
    ds.state.dispatch_debug_command({"id": 3, "command": "unknown", "arguments": {}})


if __name__ == "__main__":
    main()
