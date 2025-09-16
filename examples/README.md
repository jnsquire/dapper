# Dapper AI Debugger Examples

This directory contains examples showing how to use the Dapper AI debugger in different scenarios.

## Integrated Debugging Example

The `integrated_debugging.py` example demonstrates how to integrate the Dapper AI debugger directly into a Python program, rather than using it as an external debug adapter.

### Features Demonstrated

1. **Direct Integration**: Shows how to embed debugging capabilities into your application
2. **Programmatic Breakpoints**: Set breakpoints programmatically with conditions
3. **Event Handling**: Custom event handlers for debug events
4. **Variable Inspection**: Access and inspect variables during execution
5. **Execution Control**: Control program flow during debugging

### Usage

```bash
# Run with integrated debugging
python examples/integrated_debugging.py

# Run without debugging for comparison
python examples/integrated_debugging.py --no-debug
```

### What the Example Does

The example creates a custom debugger that:

- **Sets breakpoints** at specific lines in the code
- **Handles debug events** like breakpoints being hit and exceptions
- **Inspects variables** during execution
- **Controls execution flow** with conditional breakpoints
- **Provides real-time feedback** about the debugging process

### Key Components

- `DebugEventHandler`: Handles debug events and provides feedback
- `IntegratedDebugger`: Extends the base debugger with custom functionality
- Example functions: Demonstrate different debugging scenarios

### Use Cases

This approach is useful for:

- **Long-running applications** that need debugging capabilities
- **Custom debug interfaces** and UIs
- **Testing frameworks** that need programmatic debugging
- **Development tools** that integrate debugging features
- **Educational purposes** to understand debugging internals

### Comparison with External Debugging

| Feature | External Debugging | Integrated Debugging |
|---------|-------------------|---------------------|
| Setup | Requires debug adapter protocol | Direct code integration |
| Control | External client controls debugging | Program controls its own debugging |
| Flexibility | Limited to DAP capabilities | Full programmatic control |
| Use Case | IDE integration, remote debugging | Embedded debugging, custom tools |

## Running the Example

The example will:

1. Set up custom breakpoints
2. Run example functions with debugging enabled
3. Show breakpoint hits and variable values
4. Demonstrate exception handling
5. Provide a summary of the debug session

Output will show:
- Breakpoint setup confirmations
- Execution flow with debug events
- Variable inspection results
- Exception handling
- Session summary

## Extending the Example

You can extend this example by:

- Adding more sophisticated event handlers
- Implementing custom breakpoint conditions
- Adding variable watching capabilities
- Integrating with UI frameworks
- Adding logging and monitoring features

## Test Script

The `test_example.py` script provides a simple way to verify that the example works correctly. Run it with:

```bash
python examples/test_example.py
```

## Adapter-in-Thread Example (In-Process Mode)

Run the Debug Adapter on a background thread while your program keeps control
of the main thread. Attach with a DAP client (e.g., VS Code) using debugServer.

Files:
- `adapter_in_thread.py` — starts the adapter in a background thread on an
	ephemeral TCP port and runs a simple main-loop workload.
- `inprocess_launch.json` — sample VS Code launch configuration that sets
	`inProcess: true` and can be adapted to attach to the adapter using
	`debugServer`.

Usage:

```bash
python examples/adapter_in_thread.py
```

Then configure your DAP client to attach:
- Note the printed `tcp://127.0.0.1:<PORT>` from the script.
- In VS Code, create or adapt a launch configuration with:
	- `"request": "launch"` and `"debugServer": <PORT>`
	- `"inProcess": true` to enable in-process mode
	- Set `"program"` to the script you want to run under debug control (or
		omit if you only need attach semantics).

See `examples/inprocess_launch.json` for a minimal configuration.

## Restart Demo

`demo_restart.py` spins up a local Dapper server, launches in-process, and then
issues a `restart` request. You’ll see the response and a `terminated` event
with `restart: true` in the console output.

Run it with:

```bash
uv run python examples/demo_restart.py
```

## Attach Examples

You can attach to a running debuggee that exposes an IPC endpoint (TCP, Unix socket, or Windows named pipe). Create a VS Code configuration with `"request": "attach"`, set `useIpc: true`, and provide the appropriate transport fields (`ipcHost`/`ipcPort`, `ipcPath`, or `ipcPipeName`). See the main `README.md` for copy/paste attach snippets.

## Set Variable Demo

`demo_set_variable.py` is a simple script to try out the `setVariable` capability.
It initializes variables of different types, prints them, and suggests edits you
can make from your debugger when stopped at the marked breakpoint.

Run it with:

```powershell
uv run python examples/demo_set_variable.py
```

Tips:
- Set a breakpoint where indicated in the file (near the first print block)
- Use your debugger's Set Value / setVariable command to change values like `x`,
  `y`, `z`, `pi`, `flag`, and `data`
- Continue execution to see the "After" output reflect your changes

## Enhanced Set Variable Demo

`demo_enhanced_set_variable.py` expands on the basic demo and shows editing:
- Object attributes (e.g., `person.name`, `person.age`)
- List elements (e.g., `numbers[0]`)
- Nested dictionary values (e.g., `user_data['settings']['theme']`)
- Expression-based updates (e.g., `age = age + 1`)

Run it with:

```powershell
uv run python examples/demo_enhanced_set_variable.py
```

Set a breakpoint where indicated and try the suggested modifications listed
in the comments to exercise the enhanced behavior.

## Sample Programs

The `examples/sample_programs/` folder contains small scripts used by examples
and manual testing:

- `simple_app.py` — a minimal program with a loop and function calls
- `advanced_app.py` — a slightly richer flow for stepping and breakpoints
- `set_variable_example.py` — a concentrated target for setVariable testing

You can run them directly, for example:

```powershell
uv run python examples/sample_programs/simple_app.py
```

See `examples/sample_programs/README.md` for any additional notes.
