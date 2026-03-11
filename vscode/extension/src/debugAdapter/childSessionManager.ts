import * as vscode from 'vscode';
import * as Net from 'net';
import {
  type InternalChildLaunchConfiguration,
  type PendingChildSession,
} from './debugAdapterTypes.js';
import { ChildSessionRegistry } from './childSessionRegistry.js';
import { PendingChildConnection } from './pendingChildConnection.js';
import { DapperDebugSession, PythonDebugAdapterTransport } from './dapperDebugSession.js';

interface ChildProcessEventDetails {
  launcherSessionId: string;
  pid: number;
  ipcPort: number;
  name: string;
  cwd?: string;
  command?: string[];
}

interface ChildSessionHelloEvent {
  event: 'dapper/sessionHello';
  body?: {
    sessionId?: string;
    parentSessionId?: string;
    pid?: number;
  };
}

export class ChildSessionManager {
  private readonly _registry = new ChildSessionRegistry();
  private _sharedListener?: Net.Server;
  private _sharedListenerPort?: number;
  private _sharedListenerReady?: Promise<number>;

  public constructor(
    private readonly _getOutputChannel: () => vscode.LogOutputChannel,
    private readonly _createServer: typeof Net.createServer = Net.createServer,
  ) {}

  public hasPendingChildSession(launcherSessionId: string): boolean {
    return this._registry.has(launcherSessionId);
  }

  public getPendingChildSessionIdForPid(pid: number): string | undefined {
    return this._registry.getLauncherSessionIdForPid(pid);
  }

  public async ensureSharedListenerPort(): Promise<number> {
    if (this._sharedListenerPort != null) {
      return this._sharedListenerPort;
    }
    if (this._sharedListenerReady) {
      return this._sharedListenerReady;
    }

    this._sharedListenerReady = new Promise<number>((resolve, reject) => {
      const listener = this._createServer((socket) => {
        void this._handleSharedChildSocket(socket);
      });

      const onError = (error: Error) => {
        listener.off('listening', onListening);
        this._sharedListenerReady = undefined;
        reject(error);
      };
      const onListening = () => {
        listener.off('error', onError);
        const address = listener.address();
        if (!address || typeof address === 'string') {
          this._sharedListenerReady = undefined;
          reject(new Error('Failed to resolve shared child listener port'));
          return;
        }

        this._sharedListener = listener;
        this._sharedListenerPort = address.port;
        listener.on('error', (error) => {
          this._getOutputChannel().error(`Shared child IPC listener failed: ${error.message}`);
        });
        this._trace('child-shared-listener-ready', { port: address.port });
        this._getOutputChannel().info(`Listening for child debug sessions on 127.0.0.1:${address.port}`);
        resolve(address.port);
      };

      listener.once('error', onError);
      listener.once('listening', onListening);
      listener.listen(0, '127.0.0.1');
    });

    return this._sharedListenerReady;
  }

  public async handleChildProcessEvent(
    parentSession: vscode.DebugSession,
    body: Record<string, unknown>,
  ): Promise<void> {
    const details = this._parseChildProcessEvent(body);
    const outChannel = this._getOutputChannel();

    if (!details) {
      this._trace('child-event-malformed', body);
      outChannel.warn(`Ignoring malformed dapper/childProcess event: ${JSON.stringify(body)}`);
      return;
    }

    const { launcherSessionId, pid, ipcPort, cwd, command } = details;

    if (this.hasPendingChildSession(launcherSessionId)) {
      this._trace('child-event-duplicate', { launcherSessionId, pid, ipcPort });
      outChannel.info(`Child session ${launcherSessionId} is already being tracked`);
      return;
    }

    this._trace('child-event-accepted', {
      launcherSessionId,
      pid,
      ipcPort,
      parentDebugSessionId: parentSession.id,
      cwd,
      command,
    });

    const sharedPort = await this.ensureSharedListenerPort();
    if (ipcPort !== sharedPort) {
      this._trace('child-event-port-mismatch', { launcherSessionId, pid, ipcPort, sharedPort });
      outChannel.warn(
        `Ignoring child session ${launcherSessionId}: expected shared IPC port ${sharedPort}, got ${ipcPort}`,
      );
      return;
    }

    this._registerPendingChildSession(details, parentSession);
  }

  public handleChildProcessExitedEvent(body: Record<string, unknown>): void {
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const sessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const launcherSessionId = sessionId ?? (pid == null ? undefined : this.getPendingChildSessionIdForPid(pid));
    if (!launcherSessionId) {
      return;
    }

    const pending = this._registry.get(launcherSessionId);
    if (!pending) {
      if (pid != null) {
        this._registry.clearPid(pid);
      }
      return;
    }

    pending.connection.markTerminated();
    this._trace('child-exited-event', { launcherSessionId, pid: pid ?? pending.pid });
    if (!pending.vscodeSessionId) {
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
  }

  public handleChildProcessCandidateEvent(
    parentSession: vscode.DebugSession,
    body: Record<string, unknown>,
  ): void {
    const source = typeof body.source === 'string' ? body.source : 'unknown';
    const target = typeof body.target === 'string' ? body.target : '<unknown>';
    this._getOutputChannel().info(
      `Child-process candidate detected for session ${parentSession.id}: ${source} -> ${target}`,
    );
  }

  public handleParentSessionTerminated(session: vscode.DebugSession): void {
    const childIds = this._registry.getLauncherSessionIdsForParent(session.id);
    for (const launcherSessionId of childIds) {
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
  }

  public disposePendingChildSession(
    launcherSessionId: string,
    options: { destroySocket: boolean },
  ): void {
    const pending = this._registry.unregister(launcherSessionId);
    if (!pending) {
      return;
    }

    pending.connection.dispose(options);
  }

  public async createChildDebugAdapterDescriptor(
    session: vscode.DebugSession,
    config: InternalChildLaunchConfiguration,
  ): Promise<vscode.DebugAdapterDescriptor> {
    const pending = this._registry.get(config.__dapperChildSessionId);
    if (!pending || !pending.connection.socket) {
      this._trace('child-descriptor-missing-socket', {
        launcherSessionId: config.__dapperChildSessionId,
      });
      throw new Error(`Child debug session ${config.__dapperChildSessionId} has no pending IPC socket`);
    }

    this._trace('child-descriptor-start', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
    });

    let port: number;
    try {
      port = await pending.connection.startAdapterServer((vscodeSocket, childSocket) => {
        const sessionImpl = new DapperDebugSession(
          new PythonDebugAdapterTransport(childSocket, pending.connection.socketPrefetchBuffer),
        );
        sessionImpl.setRunAsServer(true);
        sessionImpl.start(vscodeSocket, vscodeSocket);
      });
    } catch (error) {
      this._trace('child-descriptor-listen-failed', {
        launcherSessionId: config.__dapperChildSessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      this.disposePendingChildSession(config.__dapperChildSessionId, { destroySocket: true });
      throw error;
    }

    if (this._registry.get(config.__dapperChildSessionId) !== pending || pending.connection.phase === 'terminated') {
      this.disposePendingChildSession(config.__dapperChildSessionId, { destroySocket: true });
      throw new Error(`Child debug session ${config.__dapperChildSessionId} terminated before adapter startup completed`);
    }

    pending.connection.markAdapterReady();
    pending.vscodeSessionId = session.id;

    this._trace('child-descriptor-ready', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
      port,
    });
    return new vscode.DebugAdapterServer(port, '127.0.0.1');
  }

  public dispose(): void {
    for (const launcherSessionId of this._registry.getAllLauncherSessionIds()) {
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
    this._sharedListener?.close();
    this._sharedListener = undefined;
    this._sharedListenerPort = undefined;
    this._sharedListenerReady = undefined;
  }

  private _registerPendingChildSession(
    details: ChildProcessEventDetails,
    parentSession: vscode.DebugSession,
  ): PendingChildSession {
    const pending: PendingChildSession = {
      ...details,
      parentDebugSessionId: parentSession.id,
      parentSession,
      workspaceFolder: parentSession.workspaceFolder,
      connection: new PendingChildConnection({
        launcherSessionId: details.launcherSessionId,
        pid: details.pid,
        ipcPort: details.ipcPort,
        getOutputChannel: this._getOutputChannel,
        createServer: this._createServer,
        onFatalError: (message, error) => {
          this._getOutputChannel().error(
            `${message} for ${details.launcherSessionId}: ${error instanceof Error ? error.message : String(error)}`,
          );
          this.disposePendingChildSession(details.launcherSessionId, { destroySocket: true });
        },
      }),
    };
    this._registry.register(pending);
    return pending;
  }

  private async _handleSharedChildSocket(socket: Net.Socket): Promise<void> {
    const outChannel = this._getOutputChannel();
    let buffer = Buffer.alloc(0);

    const cleanup = () => {
      socket.off('data', onData);
      socket.off('error', onError);
      socket.off('close', onClose);
    };

    const fail = (message: string, error?: unknown) => {
      cleanup();
      if (error) {
        outChannel.warn(`${message}: ${error instanceof Error ? error.message : String(error)}`);
      } else {
        outChannel.warn(message);
      }
      socket.destroy();
    };

    const onError = (error: Error) => {
      fail('Shared child socket failed during handshake', error);
    };

    const onClose = () => {
      cleanup();
    };

    const onData = (chunk: Buffer) => {
      buffer = Buffer.concat([buffer, chunk]);
      const frame = this._tryReadFrame(buffer);
      if (!frame) {
        return;
      }

      buffer = Buffer.from(frame.remainder);
      let hello: ChildSessionHelloEvent;
      try {
        hello = JSON.parse(frame.payload.toString('utf8')) as ChildSessionHelloEvent;
      } catch (error) {
        fail('Shared child socket sent invalid handshake payload', error);
        return;
      }

      const sessionId = hello.body?.sessionId;
      if (hello.event !== 'dapper/sessionHello' || typeof sessionId !== 'string' || !sessionId) {
        fail('Shared child socket sent an unexpected handshake event');
        return;
      }

      const pending = this._registry.get(sessionId);
      if (!pending) {
        fail(`Shared child socket connected for unknown session ${sessionId}`);
        return;
      }

      cleanup();
      this._trace('child-socket-connected', {
        launcherSessionId: sessionId,
        pid: pending.pid,
        ipcPort: pending.ipcPort,
      });

      if (!pending.connection.attachSocket(socket, buffer)) {
        outChannel.warn(`Child session ${sessionId} received an unexpected extra IPC connection`);
        socket.destroy();
        return;
      }

      void this._startChildDebugSession(pending).catch((error) => {
        this._trace('child-launch-failed', {
          launcherSessionId: sessionId,
          error: error instanceof Error ? error.message : String(error),
        });
        outChannel.error(
          `Failed to start child debug session for ${sessionId}: ${error instanceof Error ? error.message : String(error)}`,
        );
        this.disposePendingChildSession(sessionId, { destroySocket: true });
      });
    };

    socket.on('data', onData);
    socket.once('error', onError);
    socket.once('close', onClose);
  }

  private _tryReadFrame(buffer: Buffer): { payload: Buffer; remainder: Buffer } | undefined {
    if (buffer.length < 8) {
      return undefined;
    }

    if (buffer[0] !== 0x44 || buffer[1] !== 0x50) {
      throw new Error(
        `Invalid magic bytes in child IPC handshake: expected 0x44 0x50, got 0x${buffer[0].toString(16)} 0x${buffer[1].toString(16)}`,
      );
    }

    const length = buffer.readUInt32BE(4);
    if (buffer.length < 8 + length) {
      return undefined;
    }

    return {
      payload: buffer.subarray(8, 8 + length),
      remainder: buffer.subarray(8 + length),
    };
  }

  private async _startChildDebugSession(pending: PendingChildSession): Promise<void> {
    if (!pending.connection.markLaunchRequested()) {
      this._trace('child-launch-skipped', {
        launcherSessionId: pending.launcherSessionId,
        phase: pending.connection.phase,
        hasSocket: pending.connection.hasSocket,
      });
      return;
    }

    this._trace('child-launch-start', {
      launcherSessionId: pending.launcherSessionId,
      pid: pending.pid,
      parentDebugSessionId: pending.parentDebugSessionId,
    });

    const config = this._createChildLaunchConfiguration(pending);

    const started = pending.parentSession
      ? await vscode.debug.startDebugging(pending.workspaceFolder, config, {
          parentSession: pending.parentSession,
          compact: false,
          lifecycleManagedByParent: false,
          consoleMode: vscode.DebugConsoleMode.MergeWithParent,
        })
      : await vscode.debug.startDebugging(pending.workspaceFolder, config);

    if (!started) {
      this._trace('child-launch-declined', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
      this._getOutputChannel().error(
        `VS Code declined to start child debug session for pid=${pending.pid}`,
      );
      this.disposePendingChildSession(pending.launcherSessionId, { destroySocket: true });
    } else {
      this._trace('child-launch-requested', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
    }
  }

  private _createChildLaunchConfiguration(
    pending: PendingChildSession,
  ): InternalChildLaunchConfiguration {
    return {
      type: 'dapper',
      request: 'launch',
      name: `Dapper Child: ${pending.name} (${pending.pid})`,
      program: pending.command?.[0] || pending.name,
      cwd: pending.cwd,
      __dapperIsChildSession: true,
      __dapperChildSessionId: pending.launcherSessionId,
      __dapperChildPid: pending.pid,
      __dapperChildName: pending.name,
      __dapperParentDebugSessionId: pending.parentDebugSessionId,
      __dapperChildIpcPort: pending.ipcPort,
    };
  }

  private _parseChildProcessEvent(body: Record<string, unknown>): ChildProcessEventDetails | undefined {
    const launcherSessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const ipcPort = typeof body.ipcPort === 'number' ? body.ipcPort : undefined;
    if (!launcherSessionId || pid == null || ipcPort == null) {
      return undefined;
    }

    return {
      launcherSessionId,
      pid,
      ipcPort,
      name: typeof body.name === 'string' && body.name.length > 0 ? body.name : 'child',
      cwd: typeof body.cwd === 'string' ? body.cwd : undefined,
      command: Array.isArray(body.command)
        ? body.command.filter((value): value is string => typeof value === 'string')
        : undefined,
    };
  }

  private _trace(message: string, data?: unknown): void {
    const suffix = data === undefined ? '' : ` ${JSON.stringify(data)}`;
    this._getOutputChannel().debug(`[child-session] ${message}${suffix}`);
  }
}