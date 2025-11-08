#!/usr/bin/env python3
"""
Dapper Debug Adapter Protocol (DAP) implementation.
This script implements the Debug Adapter Protocol for the Dapper debugger.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from typing import TextIO

from dapper.constants import CONTENT_LENGTH_HEADER
from dapper.constants import MIN_CONTENT_LENGTH

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path("~").expanduser() / ".dapper-debug.log")
    ]
)
logger = logging.getLogger("dapper-debug")

class DebugAdapter:
    """Implementation of the Debug Adapter Protocol for Dapper."""
    
    def __init__(self, in_stream: TextIO, out_stream: TextIO):
        self.in_stream = in_stream
        self.out_stream = out_stream
        self.seq = 0
        self.threads: dict[int, dict[str, Any]] = {}
        self.breakpoints: dict[str, list[dict[str, Any]]] = {}
        self.running = False
        self.debug_process: subprocess.Popen | None = None
        
    def send_event(self, event: str, body: dict[str, Any] | None = None) -> None:
        """Send an event to the client."""
        message = {
            "type": "event",
            "event": event,
            "seq": self.seq,
            "body": body or {}
        }
        self.send_message(message)
    
    def send_response(self, request: dict[str, Any], body: dict[str, Any] | None = None, 
                     success: bool = True) -> None:
        """Send a response to a request."""
        message = {
            "type": "response",
            "seq": self.seq,
            "request_seq": request["seq"],
            "command": request["command"],
            "success": success,
            "message": "Success" if success else "Failed",
            "body": body or {}
        }
        self.send_message(message)
    
    def send_message(self, message: dict[str, Any]) -> None:
        """Send a message to the client."""
        content = json.dumps(message)
        content_length = len(content)
        response = f"Content-Length: {content_length}\r\n\r\n{content}"
        
        logger.debug("Sending message: %s", message)
        self.out_stream.write(response)
        self.out_stream.flush()
        self.seq += 1
    
    def handle_initialize(self, request: dict[str, Any]) -> None:
        """Handle the initialize request."""
        self.send_response(request, {
            "supportsConfigurationDoneRequest": True,
            "supportsFunctionBreakpoints": True,
            "supportsConditionalBreakpoints": True,
            "supportsHitConditionalBreakpoints": True,
            "supportsEvaluateForHovers": True,
            "supportsStepBack": False,
            "supportsSetVariable": True,
            "supportsRestartFrame": True,
            "supportsGotoTargetsRequest": False,
            "supportsStepInTargetsRequest": False,
            "supportsCompletionsRequest": True,
            "supportsModulesRequest": False,
            "supportsRestartRequest": True,
            "supportsExceptionOptions": False,
            "supportsValueFormattingOptions": True,
            "supportsExceptionInfoRequest": True,
            "supportsTerminateRequest": True,
            "supportsDelayedStackTraceLoading": True,
            "supportsLoadedSourcesRequest": True,
            "supportsLogPoints": True,
            "supportsTerminateThreadsRequest": False,
            "supportsSetExpression": False,
            "supportsTerminateDebuggee": True,
            "supportsSuspendDebuggee": True,
            "supportsCancelRequest": True,
            "supportsBreakpointLocationsRequest": True,
            "exceptionBreakpointFilters": [
                {
                    "filter": "raised",
                    "label": "Raised Exceptions",
                    "description": "Break whenever any exception is raised",
                    "default": False
                },
                {
                    "filter": "uncaught",
                    "label": "Uncaught Exceptions",
                    "description": "Break when the process is about to exit due to an unhandled exception",
                    "default": True
                }
            ]
        })
    
    def handle_launch(self, request: dict[str, Any]) -> None:
        """Handle the launch request."""
        args = request.get("arguments", {})
        program = args.get("program")
        
        if not program:
            self.send_response(request, {"error": "No program specified"}, success=False)
            return
        
        # Prepare the Python command to run
        python_path = sys.executable
        cmd = [python_path, program]
        
        # Add any command line arguments
        if args.get("args"):
            cmd.extend(args["args"])
        
        # Set up environment variables
        env = os.environ.copy()
        if args.get("env"):
            env.update(args["env"])
        
        # Set up working directory
        cwd = args.get("cwd") or str(Path(program).parent)
        
        try:
            # Start the debugged process
            self.debug_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,
                universal_newlines=True
            )
            
            # Start threads to handle process output
            threading.Thread(
                target=self._forward_output,
                args=(self.debug_process.stdout, "stdout"),
                daemon=True
            ).start()
            
            threading.Thread(
                target=self._forward_output,
                args=(self.debug_process.stderr, "stderr"),
                daemon=True
            ).start()
            
            self.running = True
            self.send_event("process", {
                "name": Path(program).name,
                "systemProcessId": self.debug_process.pid,
                "isLocalProcess": True,
                "startMethod": "launch"
            })
            
            self.send_response(request)
            
        except Exception as e:
            logger.exception("Failed to launch debug process")
            self.send_response(request, {
                "error": f"Failed to launch debug process: {e!s}"
            }, success=False)
    
    def _forward_output(self, stream: TextIO, category: str) -> None:
        """Forward process output to the debug client."""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                self.send_event("output", {
                    "category": category,
                    "output": line
                })
        except Exception:
            logger.exception("Error forwarding output")
    
    def handle_configuration_done(self, request: dict[str, Any]) -> None:
        """Handle the configurationDone request."""
        self.send_response(request)
        
        # Notify the client that the debug session is ready
        self.send_event("initialized")
    
    def handle_disconnect(self, request: dict[str, Any]) -> None:
        """Handle the disconnect request."""
        if self.debug_process and self.debug_process.poll() is None:
            self.debug_process.terminate()
            try:
                self.debug_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.debug_process.kill()
        
        self.send_response(request)
        self.running = False
    
    def handle_set_breakpoints(self, request: dict[str, Any]) -> None:
        """Handle the setBreakpoints request."""
        args = request.get("arguments", {})
        source = args.get("source", {})
        path = source.get("path", "")
        breakpoints = args.get("breakpoints", [])
        
        # Store the breakpoints
        self.breakpoints[path] = breakpoints
        
        # Send back the breakpoints with their verified state
        response_breakpoints = [{
            "verified": True,
            "line": bp.get("line", 0)
        } for bp in breakpoints]

        self.send_response(request, {
            "breakpoints": response_breakpoints
        })
    
    def handle_threads(self, request: dict[str, Any]) -> None:
        """Handle the threads request."""
        # For now, we only support a single thread
        threads = [{
            "id": 1,
            "name": "MainThread"
        }]
        
        self.send_response(request, {
            "threads": threads
        })
    
    def handle_stack_trace(self, request: dict[str, Any]) -> None:
        """Handle the stackTrace request."""
        # This is a simplified implementation
        frames = [
            {
                "id": 1,
                "name": "main",
                "source": {
                    "name": "main.py",
                    "path": "/path/to/main.py"
                },
                "line": 10,
                "column": 1
            }
        ]
        
        self.send_response(request, {
            "stackFrames": frames,
            "totalFrames": len(frames)
        })
    
    def handle_scopes(self, request: dict[str, Any]) -> None:
        """Handle the scopes request."""
        scopes = [
            {
                "name": "Local",
                "variablesReference": 1,
                "expensive": False
            }
        ]
        
        self.send_response(request, {
            "scopes": scopes
        })
    
    def handle_variables(self, request: dict[str, Any]) -> None:
        """Handle the variables request."""
        variables = [
            {
                "name": "variable1",
                "value": "value1",
                "type": "str",
                "variablesReference": 0
            },
            {
                "name": "variable2",
                "value": "42",
                "type": "int",
                "variablesReference": 0
            }
        ]
        
        self.send_response(request, {
            "variables": variables
        })
    
    def handle_continue(self, request: dict[str, Any]) -> None:
        """Handle the continue request."""
        # In a real implementation, this would resume the debugged process
        self.send_response(request)
        self.send_event("continued", {
            "threadId": 1,
            "allThreadsContinued": True
        })
    
    def handle_pause(self, request: dict[str, Any]) -> None:
        """Handle the pause request."""
        # In a real implementation, this would pause the debugged process
        self.send_response(request)
        self.send_event("stopped", {
            "reason": "pause",
            "threadId": 1,
            "allThreadsStopped": True
        })
    
    def handle_step_in(self, request: dict[str, Any]) -> None:
        """Handle the stepIn request."""
        self.send_response(request)
        self.send_event("stopped", {
            "reason": "step",
            "threadId": 1,
            "allThreadsStopped": True
        })
    
    def handle_step_out(self, request: dict[str, Any]) -> None:
        """Handle the stepOut request."""
        self.send_response(request)
        self.send_event("stopped", {
            "reason": "step",
            "threadId": 1,
            "allThreadsStopped": True
        })
    
    def handle_step_back(self, request: dict[str, Any]) -> None:
        """Handle the stepBack request."""
        # Not implemented
        self.send_response(request, {
            "error": "Step back is not supported"
        }, success=False)
    
    def handle_evaluate(self, request: dict[str, Any]) -> None:
        """Handle the evaluate request."""
        args = request.get("arguments", {})
        expression = args.get("expression", "")
        
        # In a real implementation, this would evaluate the expression in the debugged process
        self.send_response(request, {
            "result": f"Evaluated: {expression}",
            "variablesReference": 0,
            "type": "string"
        })
    
    def run(self) -> None:
        """Run the debug adapter main loop."""
        content_length = 0
        
        while True:
            # Read the content length
            line = self.in_stream.readline()
            if not line:
                break
                
            line = line.strip()
            if line.startswith(CONTENT_LENGTH_HEADER):
                content_length = int(line[len(CONTENT_LENGTH_HEADER):])
            elif line == "" and content_length > MIN_CONTENT_LENGTH:
                content = self.in_stream.read(content_length)
                try:
                    message = json.loads(content)
                    self.handle_message(message)
                except json.JSONDecodeError:
                    msg = "Failed to parse message"
                    logger.exception(msg)
                    continue
        
        logger.info("Debug adapter shutting down")
    
    def handle_message(self, message: dict[str, Any]) -> None:
        """Handle a message from the client."""
        logger.debug("Received message: %s", message)
        
        command = message.get("command", "")
        handler_name = f"handle_{command.lower()}"
        handler = getattr(self, handler_name, None)
        
        if handler:
            try:
                handler(message)
            except Exception as e:
                logger.exception(f"Error handling {command} request")
                self.send_response(message, {
                    "error": f"Error handling {command} request: {e!s}"
                }, success=False)
        else:
            self.send_response(message, {
                "error": f"Unknown command: {command}"
            }, success=False)


def main() -> None:
    """Main entry point for the debug adapter."""
    parser = argparse.ArgumentParser(description="Dapper Debug Adapter")
    parser.add_argument("--server", action="store_true", help="Run in server mode")
    args = parser.parse_args()
    
    if args.server:
        # In server mode, listen on stdin/stdout
        adapter = DebugAdapter(sys.stdin, sys.stdout)
        adapter.run()
    else:
        print("Dapper Debug Adapter - Use --server to run in server mode", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
