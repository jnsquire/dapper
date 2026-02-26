# Debug Adapter: Operational Modes (diagrams)

This reference page consolidates the adapter operational diagrams that show Launch, Attach and In-Process modes, IPC transports, message flows, backend-selection and threading models.

---

## 1. Launch Mode Architecture

```mermaid
graph TB
    subgraph "VS Code / DAP Client"
        Client[Debug Adapter Client]
    end
    
    subgraph "Dapper Debug Adapter Process"
        Adapter[DebugAdapterServer]
        Handler[RequestHandler]
        Debugger[PyDebugger]
        IPC_Mgr[IPCManager]
    end
    
    subgraph "Debuggee Process (New Subprocess)"
        Launcher[debug_launcher.py]
        Debuggee[User Program]
        IPC_Bridge[IPC Bridge]
    end
    
    Client -->|DAP Protocol| Adapter
    Adapter --> Handler
    Handler --> Debugger
    Debugger --> IPC_Mgr
    
    IPC_Mgr -.->|IPC Transport| IPC_Bridge
    IPC_Bridge --> Launcher
    Launcher --> Debuggee
    
    Debuggee -.->|Debug Events| Launcher
    Launcher -.->|IPC Messages| IPC_Mgr
    IPC_Mgr --> Debugger
    Debugger --> Handler
    Handler --> Adapter
    Adapter --> Client
```

### Launch Mode Flow

```mermaid
sequenceDiagram
    participant Client as DAP Client
    participant Adapter as DebugAdapterServer
    participant Debugger as PyDebugger
    participant IPC as IPCManager
    participant Launcher as debug_launcher.py
    participant Debuggee as User Program
    
    Client->>Adapter: launch request
    Adapter->>Debugger: launch()
    Debugger->>IPC: create_listener()
    IPC-->>Debugger: IPC args
    Debugger->>Launcher: start subprocess
    Launcher->>Debuggee: exec user program
    
    Debuggee->>Launcher: breakpoint hit
    Launcher->>IPC: send debug event
    IPC->>Debugger: handle message
    Debugger->>Adapter: stopped event
    Adapter->>Client: stopped event
    
    Client->>Adapter: continue request
    Adapter->>Debugger: continue()
    Debugger->>IPC: write command
    IPC->>Launcher: continue command
    Launcher->>Debuggee: resume execution
```

---

## 2. Attach Mode Architecture

```mermaid
graph TB
    subgraph "VS Code / DAP Client"
        Client[Debug Adapter Client]
    end
    
    subgraph "Dapper Debug Adapter Process"
        Adapter[DebugAdapterServer]
        Handler[RequestHandler]
        Debugger[PyDebugger]
        IPC_Mgr[IPCManager]
    end
    
    subgraph "Existing Debuggee Process"
        Launcher[debug_launcher.py]
        Debuggee[User Program]
        IPC_Bridge[IPC Bridge]
    end
    
    Client -->|DAP Protocol| Adapter
    Adapter --> Handler
    Handler --> Debugger
    Debugger --> IPC_Mgr
    
    IPC_Mgr -->|Connect to existing| IPC_Bridge
    IPC_Bridge --> Launcher
    Launcher --> Debuggee
    
    Debuggee -.->|Debug Events| Launcher
    Launcher -.->|IPC Messages| IPC_Mgr
    IPC_Mgr --> Debugger
    Debugger --> Handler
    Handler --> Adapter
    Adapter --> Client
```

### Attach Mode Flow

```mermaid
sequenceDiagram
    participant Client as DAP Client
    participant Adapter as DebugAdapterServer
    participant Debugger as PyDebugger
    participant IPC as IPCManager
    participant Launcher as debug_launcher.py
    participant Debuggee as User Program
    
    Note over Client,Debuggee: Debuggee already running
    
    Client->>Adapter: attach request
    Adapter->>Debugger: attach()
    Debugger->>IPC: connect()
    IPC->>Launcher: establish connection
    
    Debuggee->>Launcher: breakpoint hit
    Launcher->>IPC: send debug event
    IPC->>Debugger: handle message
    Debugger->>Adapter: stopped event
    Adapter->>Client: stopped event
    
    Client->>Adapter: continue request
    Adapter->>Debugger: continue()
    Debugger->>IPC: write command
    IPC->>Launcher: continue command
    Launcher->>Debuggee: resume execution
```

---

## 3. In-Process Mode Architecture

```mermaid
graph TB
    subgraph "VS Code / DAP Client"
        Client[Debug Adapter Client]
    end
    
    subgraph "Dapper Debug Adapter Process (Same as Debuggee)"
        Adapter[DebugAdapterServer]
        Handler[RequestHandler]
        Debugger[PyDebugger]
        InProc[InProcessDebugger]
        Bridge[InProcessBridge]
        Backend[InProcessBackend]
        UserCode[User Code]
    end
    
    Client -->|DAP Protocol| Adapter
    Adapter --> Handler
    Handler --> Debugger
    Debugger --> Backend
    Backend --> Bridge
    Bridge --> InProc
    InProc --> UserCode
    
    UserCode -.->|Direct Events| InProc
    InProc -.->|Bridge Events| Bridge
    Bridge --> Backend
    Backend --> Debugger
    Debugger --> Handler
    Handler --> Adapter
    Adapter --> Client
```

### In-Process Mode Flow

```mermaid
sequenceDiagram
    participant Client as DAP Client
    participant Adapter as DebugAdapterServer
    participant Debugger as PyDebugger
    participant Backend as InProcessBackend
    participant Bridge as InProcessBridge
    participant InProc as InProcessDebugger
    participant UserCode as User Code
    
    Client->>Adapter: launch request (inProcess: true)
    Adapter->>Debugger: launch(in_process: true)
    Debugger->>Debugger: _launch_in_process()
    Debugger->>InProc: create InProcessDebugger
    Debugger->>Bridge: create InProcessBridge
    Debugger->>Backend: create InProcessBackend
    Adapter->>Client: process event (no subprocess)
    
    UserCode->>InProc: breakpoint hit
    InProc->>Bridge: stopped event
    Bridge->>Backend: handle event
    Backend->>Debugger: handle event
    Debugger->>Adapter: stopped event
    Adapter->>Client: stopped event
    
    Client->>Adapter: continue request
    Adapter->>Debugger: continue()
    Debugger->>Backend: continue()
    Backend->>Bridge: continue()
    Bridge->>InProc: continue execution
    InProc->>UserCode: resume
```

---

## 4. IPC Transport Mechanisms

### Windows Named Pipes

```mermaid
graph LR
    subgraph "Debug Adapter"
        DA[DebugAdapterServer]
        PipeListener[mp_conn.Listener]
    end
    
    subgraph "Debuggee"
        PipeClient[mp_conn.Client]
        Launcher[debug_launcher.py]
    end
    
    DA --> PipeListener
    PipeListener -.->|Named Pipe| PipeClient
    PipeClient --> Launcher
```

### Unix Domain Sockets

```mermaid
graph LR
    subgraph "Debug Adapter"
        DA[DebugAdapterServer]
        UnixListener[socket.AF_UNIX]
    end
    
    subgraph "Debuggee"
        UnixClient[socket.AF_UNIX]
        Launcher[debug_launcher.py]
    end
    
    DA --> UnixListener
    UnixListener -.->|Unix Socket| UnixClient
    UnixClient --> Launcher
```

### TCP Sockets

```mermaid
graph LR
    subgraph "Debug Adapter"
        DA[DebugAdapterServer]
        TCPListener[socket.AF_INET]
    end
    
    subgraph "Debuggee"
        TCPClient[socket.AF_INET]
        Launcher[debug_launcher.py]
    end
    
    DA --> TCPListener
    TCPListener -.->|TCP Connection| TCPClient
    TCPClient --> Launcher
```

---

## 5. Child Process Auto-Attach (Phase 1)

When launch config includes `subprocessAutoAttach: true`, the launcher enables
child process interception for Python `subprocess.Popen(...)` calls.

### Launch argument

- `subprocessAutoAttach` (`boolean`, default `false`)

### Custom events emitted to DAP client

`dapper/childProcess`

- Emitted when a Python child process is detected and rewritten for Dapper launch.
- Event body fields:
    - `pid` (`number`) child process id
    - `name` (`string`) inferred child program name
    - `ipcPort` (`number`) allocated TCP port for child IPC
    - `command` (`string[]`) original child command args
    - `cwd` (`string | null`) child working directory if provided
    - `isPython` (`boolean`) whether child command was Python
    - `parentPid` (`number`) parent process id
    - `sessionId` (`string | null`) optional logical session identifier
    - `parentSessionId` (`string | null`) optional parent session identifier

`dapper/childProcessExited`

- Emitted when a tracked child exits.
- Event body fields:
    - `pid` (`number`) child process id
    - `name` (`string`) child process name

`dapper/childProcessCandidate` (Phase 2 scaffold)

- Emitted when a potential child-process source is detected in APIs not yet
    fully auto-attached.
- Event body fields:
    - `source` (`string`) detector source (for example,
        `multiprocessing.Process` or `concurrent.futures.ProcessPoolExecutor`)
    - `name` (`string`) process/executor display name
    - `target` (`string | null`) best-effort target callable name
    - `parentPid` (`number`) parent process id
    - `sessionId` (`string | null`) current logical session identifier
    - `parentSessionId` (`string | null`) parent logical session identifier
    - `autoAttachImplemented` (`boolean`) whether full auto-attach is currently implemented

### Notes

- Current implementation scope is `subprocess.Popen` interception for Python commands.
- Python script/module/code child invocations (`python script.py`, `python -m ...`, `python -c ...`) are rewritten to Dapper launcher form for auto-attach.
- `multiprocessing.Process` and `ProcessPoolExecutor` currently emit
    `dapper/childProcessCandidate` scaffold events only; full launcher injection is pending.
- In many runtimes, `multiprocessing` / `ProcessPoolExecutor` worker launches pass through `subprocess.Popen` and are auto-attached via the Python `-c` rewrite path.
- Non-Python children are not auto-attached.
- `shell=True` and stdin-script (`python -`) invocation forms are still passed through.
- Event forwarding is adapter-specific (`dapper/*` namespace) and follows DAP custom event semantics.

---

## 6. Message Flow Patterns

### Binary vs Text Protocol

```mermaid
graph TB
    subgraph "Binary Protocol"
        Binary[Binary Frame]
        Magic[MAGIC: "DP"]
        Ver[VERSION: 1]
        Kind[KIND: 1=event, 2=command]
        Len[LENGTH: 4 bytes]
        Payload[Payload Data]
        
        Binary --> Magic
        Magic --> Ver
        Ver --> Kind
        Kind --> Len
        Len --> Payload
    end
    
    subgraph "Text Protocol"
        Text[Text Line]
        Prefix["DBGP: "]
        JSON[JSON Message]
        
        Text --> Prefix
        Prefix --> JSON
    end
```

### Request-Response Pattern

```mermaid
sequenceDiagram
    participant Client as DAP Client
    participant Adapter as DebugAdapterServer
    participant Backend as Debugger Backend
    participant Debuggee as Debuggee Process
    
    Client->>Adapter: DAP Request
    Adapter->>Backend: translate to debug command
    Backend->>Debuggee: send via IPC
    Debuggee-->>Backend: debug response
    Backend-->>Adapter: translate to DAP response
    Adapter-->>Client: DAP Response
    
    Note over Client,Debuggee: Async communication throughout
```

---

## 7. Backend Selection Logic

```mermaid
flowchart TD
    Start[Launch/Attach Request] --> CheckInProcess{in_process: true?}
    
    CheckInProcess -->|Yes| CreateInProc[Create InProcessBackend]
    CheckInProcess -->|No| CheckExternal{External Process?}
    
    CheckExternal -->|Launch| CreateExternal[Create ExternalProcessBackend]
    CheckExternal -->|Attach| UseExisting[Use Existing Backend]
    
    CreateInProc --> InProcReady[In-Process Backend Ready]
    CreateExternal --> ExternalReady[External Process Backend Ready]
    UseExisting --> ExternalReady
    
    InProcReady --> End[Backend Selected]
    ExternalReady --> End
```

---

## 8. Error Handling and Cleanup

```mermaid
stateDiagram-v2
    [*] --> Initializing
    
    Initializing --> Launching: launch request
    Initializing --> Attaching: attach request
    Initializing --> InProcess: in_process launch
    
    Launching --> Running: process started
    Attaching --> Running: connection established
    InProcess --> Running: bridge created
    
    Running --> Error: IPC failure
    Running --> Terminating: disconnect/terminate
    
    Error --> Cleaning: cleanup resources
    Terminating --> Cleaning: cleanup resources
    
    Cleaning --> [*]: cleanup complete
    
    Running --> Running: normal operation
```

---

## 9. Configuration Matrix

| Mode | IPC Required | Subprocess | Backend Type | Use Case |
|------|--------------|------------|--------------|----------|
| Launch (Default) | Yes | Yes | ExternalProcessBackend | Standard debugging |
| Launch (inProcess) | No | No | InProcessBackend | Embedded debugging |
| Attach | Yes | No | ExternalProcessBackend | Connect to existing; supports `pathMappings` for remote |
| No Debug | No | Yes | None | Run without debugging |
| Hot Reload | Yes (active) | N/A | N/A | Live code reload while session is paused |

---

## 10. Threading Model

```mermaid
graph TB
    subgraph "Main Thread"
        Main[DebugAdapterServer]
        EventLoop[AsyncIO Event Loop]
    end
    
    subgraph "IPC Reader Thread"
        Reader[IPC Reader Thread]
        IPC_Receive[Receive Messages]
    end
    
    subgraph "Debuggee Process"
        DebuggeeThread[User Code Thread]
        DebuggerThread[Debugger Thread]
    end
    
    Main --> EventLoop
    EventLoop --> Reader
    Reader --> IPC_Receive
    IPC_Receive --> EventLoop
    
    DebuggeeThread --> DebuggerThread
    DebuggerThread -.->|IPC Events| IPC_Receive
```

---

## 11. Hot Reload

Hot reload allows a Python source file to be reloaded into the running process without stopping or restarting the debug session. It is only available while the session is paused (stopped state).

### Triggers

- **Manual** — `Dapper: Hot Reload Current File` command (`Ctrl+Alt+R` / `Cmd+Alt+R`).
- **Auto on save** — when `dapper.hotReload.autoOnSave` is `true` (default), saving a Python file that is loaded in the active stopped session triggers a reload automatically.

### Custom DAP messages

`dapper/hotReload` (request from extension → adapter)

- Request body fields:
    - `source.path` (`string`) absolute path of the file to reload

`dapper/hotReloadResult` (event from adapter → extension)

- Event body fields:
    - `reloadedModule` (`string`) Python module name that was reloaded
    - `reboundFrames` (`number`) number of live stack frames rebound to new code
    - `updatedFrameCodes` (`number`) number of code objects updated
    - `warnings` (`string[]`) non-fatal warnings produced during reload

### Manual hot reload flow

```mermaid
sequenceDiagram
    participant Editor as VS Code Editor
    participant Ext as Dapper Extension
    participant Session as Debug Session
    participant Adapter as DapperDebugSession
    participant Python as Python Debug Adapter

    Editor->>Ext: dapper.hotReload (Ctrl+Alt+R)
    Ext->>Editor: document.save()
    Ext->>Session: customRequest('dapper/hotReload', {source: {path}})
    Session->>Adapter: dapper/hotReload request
    Adapter->>Python: IPC hot reload command
    Python-->>Adapter: reload result
    Adapter-->>Session: dapper/hotReloadResult event
    Session-->>Ext: event received
    Ext->>Editor: showInformationMessage (reloadedModule, reboundFrames, updatedFrameCodes)
    Note over Ext: warnings shown as separate warning message if non-empty
```

### Auto hot reload flow (on save)

```mermaid
sequenceDiagram
    participant Editor as VS Code Editor
    participant Ext as Dapper Extension
    participant Session as Debug Session
    participant Adapter as DapperDebugSession
    participant Python as Python Debug Adapter

    Note over Ext: dapper.hotReload.autoOnSave=true
    Editor->>Ext: onDidSaveTextDocument
    Ext->>Ext: check: python file, active dapper session, session stopped?
    Ext->>Session: loadedSources request
    Session-->>Ext: loaded source list
    Ext->>Ext: check: saved file in loaded sources?
    Ext->>Session: customRequest('dapper/hotReload', {source: {path}})
    Session->>Adapter: dapper/hotReload request
    Adapter->>Python: IPC hot reload command
    Python-->>Adapter: reload result
    Adapter-->>Ext: dapper/hotReloadResult event
    Ext->>Editor: setStatusBarMessage (Auto reloaded <file>)
```
