<!-- Manual testing guide migrated into Getting Started -->

# Testing Dapper Debug Adapter - Manual Process

This guide shows how to manually test your Dapper debug adapter by connecting to it as an external debug adapter (the way VS Code would).

## 🚀 Quick Start

### Method 1: Two Terminal Process

**Terminal 1** (Start debug adapter):
```bash
python -m dapper --port 4711 --log-level DEBUG
```

**Terminal 2** (Test connection):
```bash
python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py
```

**Terminal 2** (Run full debug session):
```bash
python test_dapper_client.py --program examples/sample_programs/simple_app.py
```

### Method 2: VS Code Integration

1. **Start the debug adapter**:
   - Open Run and Debug panel (Ctrl+Shift+D)
   - Select "Launch Debug Adapter (TCP)"
   - Click the green play button

2. **Connect and debug**:
   - Open a new VS Code window or use a separate terminal
   - Select "Test Dapper Debug Adapter" configuration
   - This will run a DAP client that connects to your adapter

## 📋 Step-by-Step Process

### Step 1: Launch Debug Adapter

Start your debug adapter in server mode:

```bash
python -m dapper --port 4711 --log-level DEBUG
```

You should see output like:
```
2025-09-08 [INFO] dapper.adapter: Starting debug adapter with tcp connection
2025-09-08 [INFO] dapper.connection: TCP server listening on localhost:4711
```

### Step 2: Test Connection

Verify the adapter is running:

```bash
python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py
```

Expected output:
```
🔍 Testing connection to debug adapter at localhost:4711...
✅ Debug adapter is running and accepting connections
✅ Connection test successful!
```

### Step 3: Run Debug Session

Connect to your adapter and debug a program:

```bash
python test_dapper_client.py --program examples/sample_programs/simple_app.py
```

This will:
1. Connect to your debug adapter on port 4711
2. Send DAP `initialize` request
3. Send DAP `launch` request for the target program
4. Set breakpoints at lines 70 and 85
5. Send `configurationDone` and `continue` requests

## 🔍 What to Watch For

### Debug Adapter Logs

In the terminal running the debug adapter, you should see:
```
2025-09-08 [DEBUG] dapper.server: Received request: initialize
2025-09-08 [DEBUG] dapper.server: Received request: launch
2025-09-08 [DEBUG] dapper.server: Received request: setBreakpoints
2025-09-08 [DEBUG] dapper.server: Received request: configurationDone
2025-09-08 [DEBUG] dapper.server: Received request: continue
```

### Client Output

The test client shows the DAP communication:
```
📤 Sending: initialize
   {"seq": 1, "type": "request", "command": "initialize", "arguments": {...}}
📥 Received: response
   {"seq": 1, "type": "response", "success": true, ...}
```

## 🧪 Testing Different Scenarios

### Test Simple Program

```bash
python test_dapper_client.py --program examples/sample_programs/simple_app.py
```

### Test Advanced Program  

```bash
python test_dapper_client.py --program examples/sample_programs/advanced_app.py
```

### Test with Different Port

```bash
# Start adapter on different port
python -m dapper --port 5555

# Connect to different port
python test_dapper_client.py --port 5555 --program examples/sample_programs/simple_app.py
```

### Test Subprocess IPC Transports

You can run the debuggee in a subprocess and have the adapter↔launcher
communicate over IPC. The server forwards `useIpc` and transport options
to the launcher automatically.

- Windows (default: named pipe)
   - In your client (or launch request), set: `{"useIpc": true}`
   - The launcher will receive `--ipc pipe --ipc-pipe \\\\.\\pipe\\dapper-...`
   - Verify cleanup: on terminate, the pipe endpoints are closed.

- macOS/Linux (default: UNIX domain socket, TCP fallback)
   - In your client (or launch request), set: `{"useIpc": true}`
   - The launcher will receive `--ipc unix --ipc-path /tmp/dapper-....sock`
   - Verify cleanup: the `.sock` file is removed on terminate.

Force a specific transport when needed:

```jsonc
// Example DAP launch arguments
{
   "program": "examples/sample_programs/simple_app.py",
   "useIpc": true,
   "ipcTransport": "tcp", // or "pipe" (Windows), "unix" (POSIX)
}
```

Notes:
- If `ipcTransport` is omitted: Windows defaults to `pipe`; non-Windows
   defaults to `unix` and falls back to TCP when AF_UNIX is unavailable.
- The server only forwards IPC-related kwargs to the launcher when
   `useIpc` is true to preserve legacy argument ordering.

## 🔧 VS Code Launch Configurations

The `.vscode/launch.json` includes these configurations:

| Configuration | Purpose |
|---------------|---------|
| `Launch Debug Adapter (TCP)` | Start your Dapper adapter on port 4711 |
| `Test Dapper Debug Adapter` | Run the DAP client to test your adapter |
| `Debug Simple App (Standard Python)` | Compare with VS Code's debugger |

## 📊 Comparing with Standard Debugger

To verify your adapter works correctly:

1. **Debug with your adapter**:
   - Start: "Launch Debug Adapter (TCP)"
   - Run: "Test Dapper Debug Adapter"

2. **Debug with VS Code's debugger**:
   - Run: "Debug Simple App (Standard Python)"

3. **Compare the behavior**:
   - Breakpoints hit at same lines
   - Variable values match
   - Step operations work similarly

## 🐛 Troubleshooting

### Connection Refused

```
❌ Failed to connect to debug adapter: [Errno 10061] No connection could be made
```

**Solution**: Make sure the debug adapter is running first.

### Port Already in Use

```
❌ [Errno 10048] Only one usage of each socket address is normally permitted
```

**Solution**: Kill existing processes or use a different port.

### No Response from Adapter

If the client hangs waiting for a response:
1. Check debug adapter logs for errors
2. Verify your adapter implements the required DAP requests
3. Use `--log-level DEBUG` for detailed logging

### Invalid DAP Messages

```
❌ Error during debug session: JSON decode error
```

**Solution**: Check that your adapter sends properly formatted DAP responses.

## 📝 Next Steps

1. **Implement missing DAP requests** in your adapter
2. **Add more test scenarios** to the client
3. **Test edge cases** like invalid programs, connection drops, etc.
4. **Add breakpoint functionality** to see actual debugging in action
5. **Test variable inspection** and stepping operations

This manual testing process helps verify that your debug adapter correctly implements the Debug Adapter Protocol! 🎉
