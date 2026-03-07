import * as vscode from 'vscode';
import * as Net from 'net';
import * as os from 'os';
import * as fs from 'fs';
import { join as pathJoin } from 'path';
import {
  type InternalChildLaunchConfiguration,
  type PendingChildSession,
} from './debugAdapterTypes.js';
import { DapperDebugSession, PythonDebugAdapterTransport } from './dapperDebugSession.js';

const CHILD_ATTACH_TRACE_PATH = pathJoin(os.tmpdir(), 'dapper-child-attach.log');

function traceChildAttach(message: string, data?: unknown): void {
  try {
    const payload = data === undefined ? '' : ` ${JSON.stringify(data)}`;
    fs.appendFileSync(
      CHILD_ATTACH_TRACE_PATH,
      `${new Date().toISOString()} ${message}${payload}\n`,
      'utf8',
    );
  } catch {
    // Best-effort debug tracing only.
  }
}

export class ChildSessionManager {
  private readonly _childSessions = new Map<string, PendingChildSession>();
  private readonly _childSessionIdsByPid = new Map<number, string>();

  public constructor(
    private readonly _getOutputChannel: () => vscode.LogOutputChannel,
  ) {}

  public get childSessions(): Map<string, PendingChildSession> {
    return this._childSessions;
  }

  public get childSessionIdsByPid(): Map<number, string> {
    return this._childSessionIdsByPid;
  }

  public async handleChildProcessEvent(
    parentSession: vscode.DebugSession,
    body: Record<string, unknown>,
  ): Promise<void> {
    const launcherSessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const ipcPort = typeof body.ipcPort === 'number' ? body.ipcPort : undefined;
    const name = typeof body.name === 'string' && body.name.length > 0 ? body.name : 'child';
    const cwd = typeof body.cwd === 'string' ? body.cwd : undefined;
    const command = Array.isArray(body.command)
      ? body.command.filter((value): value is string => typeof value === 'string')
      : undefined;
    const outChannel = this._getOutputChannel();

    if (!launcherSessionId || pid == null || ipcPort == null) {
      traceChildAttach('child-event-malformed', body);
      outChannel.warn(`Ignoring malformed dapper/childProcess event: ${JSON.stringify(body)}`);
      return;
    }

    if (this._childSessions.has(launcherSessionId)) {
      traceChildAttach('child-event-duplicate', { launcherSessionId, pid, ipcPort });
      outChannel.info(`Child session ${launcherSessionId} is already being tracked`);
      return;
    }

    traceChildAttach('child-event-accepted', {
      launcherSessionId,
      pid,
      ipcPort,
      parentDebugSessionId: parentSession.id,
      cwd,
      command,
    });

    const pending: PendingChildSession = {
      launcherSessionId,
      pid,
      name,
      ipcPort,
      parentDebugSessionId: parentSession.id,
      parentSession,
      workspaceFolder: parentSession.workspaceFolder,
      cwd,
      command,
    };
    this._childSessions.set(launcherSessionId, pending);
    this._childSessionIdsByPid.set(pid, launcherSessionId);

    const listener = Net.createServer((socket) => {
      const current = this._childSessions.get(launcherSessionId);
      if (!current || current.terminated) {
        traceChildAttach('child-socket-rejected', { launcherSessionId, reason: 'terminated-or-missing' });
        socket.destroy();
        return;
      }

      if (current.socket) {
        traceChildAttach('child-socket-rejected', { launcherSessionId, reason: 'duplicate-connection' });
        outChannel.warn(`Child session ${launcherSessionId} received an unexpected extra IPC connection`);
        socket.destroy();
        return;
      }

      current.socket = socket;
      if (current.listener) {
        current.listener.close();
        current.listener = undefined;
      }

      outChannel.info(`Child process ${current.pid} connected on 127.0.0.1:${current.ipcPort}`);
      traceChildAttach('child-socket-connected', {
        launcherSessionId,
        pid: current.pid,
        ipcPort: current.ipcPort,
      });
      void this._startChildDebugSession(current).catch((error) => {
        traceChildAttach('child-launch-failed', {
          launcherSessionId,
          error: error instanceof Error ? error.message : String(error),
        });
        outChannel.error(
          `Failed to start child debug session for ${launcherSessionId}: ${error instanceof Error ? error.message : String(error)}`,
        );
        this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
      });
    });

    await new Promise<void>((resolve, reject) => {
      const onError = (error: Error) => {
        listener.off('listening', onListening);
        reject(error);
      };
      const onListening = () => {
        listener.off('error', onError);
        resolve();
      };

      listener.once('error', onError);
      listener.once('listening', onListening);
      listener.listen(ipcPort, '127.0.0.1');
    }).catch((error) => {
      traceChildAttach('child-listener-listen-failed', {
        launcherSessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
      throw error;
    });

    listener.on('error', (error) => {
      traceChildAttach('child-listener-runtime-error', {
        launcherSessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      outChannel.error(
        `Child IPC listener failed for ${launcherSessionId}: ${error instanceof Error ? error.message : String(error)}`,
      );
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    });

    pending.listener = listener;
    traceChildAttach('child-listener-ready', { launcherSessionId, pid, ipcPort });
    outChannel.info(`Listening for child process ${pid} on 127.0.0.1:${ipcPort}`);
  }

  public handleChildProcessExitedEvent(body: Record<string, unknown>): void {
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const sessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const launcherSessionId = sessionId ?? (pid == null ? undefined : this._childSessionIdsByPid.get(pid));
    if (!launcherSessionId) {
      return;
    }

    const pending = this._childSessions.get(launcherSessionId);
    if (!pending) {
      if (pid != null) {
        this._childSessionIdsByPid.delete(pid);
      }
      return;
    }

    pending.terminated = true;
    traceChildAttach('child-exited-event', { launcherSessionId, pid: pid ?? pending.pid });
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
    const childIds = [...this._childSessions.values()]
      .filter((pending) => pending.parentDebugSessionId === session.id)
      .map((pending) => pending.launcherSessionId);
    for (const launcherSessionId of childIds) {
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
  }

  public disposePendingChildSession(
    launcherSessionId: string,
    options: { destroySocket: boolean },
  ): void {
    const pending = this._childSessions.get(launcherSessionId);
    if (!pending) {
      return;
    }

    pending.terminated = true;
    if (pending.listener) {
      pending.listener.close();
      pending.listener = undefined;
    }
    if (pending.adapterServer) {
      pending.adapterServer.close();
      pending.adapterServer = undefined;
    }
    if (options.destroySocket && pending.socket && !pending.socket.destroyed) {
      pending.socket.destroy();
    }

    this._childSessions.delete(launcherSessionId);
    this._childSessionIdsByPid.delete(pending.pid);
  }

  public async createChildDebugAdapterDescriptor(
    session: vscode.DebugSession,
    config: InternalChildLaunchConfiguration,
  ): Promise<vscode.DebugAdapterDescriptor> {
    const pending = this._childSessions.get(config.__dapperChildSessionId);
    if (!pending || !pending.socket) {
      traceChildAttach('child-descriptor-missing-socket', {
        launcherSessionId: config.__dapperChildSessionId,
      });
      throw new Error(`Child debug session ${config.__dapperChildSessionId} has no pending IPC socket`);
    }

    pending.vscodeSessionId = session.id;
    traceChildAttach('child-descriptor-start', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
    });

    const adapterServer = Net.createServer((vscodeSocket) => {
      adapterServer.close();
      pending.adapterServer = undefined;
      const sessionImpl = new DapperDebugSession(new PythonDebugAdapterTransport(pending.socket));
      sessionImpl.setRunAsServer(true);
      sessionImpl.start(vscodeSocket, vscodeSocket);
    });

    const port = await new Promise<number>((resolve, reject) => {
      const onError = (error: Error) => {
        adapterServer.off('listening', onListening);
        reject(error);
      };
      const onListening = () => {
        adapterServer.off('error', onError);
        resolve((adapterServer.address() as Net.AddressInfo).port);
      };

      adapterServer.once('error', onError);
      adapterServer.once('listening', onListening);
      adapterServer.listen(0, '127.0.0.1');
    });

    adapterServer.on('error', (error) => {
      this._getOutputChannel().error(
        `Child debug adapter server failed for ${config.__dapperChildSessionId}: ${error instanceof Error ? error.message : String(error)}`,
      );
      this.disposePendingChildSession(config.__dapperChildSessionId, { destroySocket: true });
    });

    pending.adapterServer = adapterServer;
    traceChildAttach('child-descriptor-ready', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
      port,
    });
    return new vscode.DebugAdapterServer(port, '127.0.0.1');
  }

  public dispose(): void {
    for (const launcherSessionId of [...this._childSessions.keys()]) {
      this.disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
  }

  private async _startChildDebugSession(pending: PendingChildSession): Promise<void> {
    if (pending.launchRequested || pending.terminated || !pending.socket) {
      traceChildAttach('child-launch-skipped', {
        launcherSessionId: pending.launcherSessionId,
        launchRequested: pending.launchRequested,
        terminated: pending.terminated,
        hasSocket: Boolean(pending.socket),
      });
      return;
    }

    pending.launchRequested = true;
    traceChildAttach('child-launch-start', {
      launcherSessionId: pending.launcherSessionId,
      pid: pending.pid,
      parentDebugSessionId: pending.parentDebugSessionId,
    });

    const config: InternalChildLaunchConfiguration = {
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

    const started = pending.parentSession
      ? await vscode.debug.startDebugging(pending.workspaceFolder, config, {
          parentSession: pending.parentSession,
          compact: false,
          lifecycleManagedByParent: false,
          consoleMode: vscode.DebugConsoleMode.MergeWithParent,
        })
      : await vscode.debug.startDebugging(pending.workspaceFolder, config);

    if (!started) {
      traceChildAttach('child-launch-declined', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
      this._getOutputChannel().error(
        `VS Code declined to start child debug session for pid=${pending.pid}`,
      );
      this.disposePendingChildSession(pending.launcherSessionId, { destroySocket: true });
    } else {
      traceChildAttach('child-launch-requested', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
    }
  }
}