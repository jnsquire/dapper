import * as Net from 'net';
import * as vscode from 'vscode';

export type PendingChildConnectionPhase = 'listening' | 'connected' | 'launch-requested' | 'adapter-ready' | 'terminated';

interface PendingChildConnectionOptions {
  launcherSessionId: string;
  pid: number;
  ipcPort: number;
  getOutputChannel: () => vscode.LogOutputChannel;
  createServer?: typeof Net.createServer;
  onFatalError: (message: string, error: unknown) => void;
}

export class PendingChildConnection {
  private readonly _createServer: typeof Net.createServer;
  private _socket?: Net.Socket;
  private _socketPrefetchBuffer: Buffer = Buffer.alloc(0);
  private _adapterServer?: Net.Server;
  private _phase: PendingChildConnectionPhase = 'listening';

  public constructor(private readonly _options: PendingChildConnectionOptions) {
    this._createServer = _options.createServer ?? Net.createServer;
  }

  public get phase(): PendingChildConnectionPhase {
    return this._phase;
  }

  public get socket(): Net.Socket | undefined {
    return this._socket;
  }

  public get socketPrefetchBuffer(): Buffer {
    return this._socketPrefetchBuffer;
  }

  public get hasSocket(): boolean {
    return Boolean(this._socket);
  }

  public attachSocket(socket: Net.Socket, initialBuffer: Buffer = Buffer.alloc(0)): boolean {
    if (this._phase === 'terminated' || this._socket) {
      return false;
    }

    this._socket = socket;
    this._socketPrefetchBuffer = initialBuffer;
    this._phase = 'connected';
    this._options.getOutputChannel().info(
      `Child process ${this._options.pid} connected on 127.0.0.1:${this._options.ipcPort}`,
    );
    return true;
  }

  public markLaunchRequested(): boolean {
    if (this._phase !== 'connected' || !this._socket) {
      return false;
    }
    this._phase = 'launch-requested';
    return true;
  }

  public markAdapterReady(): void {
    this._phase = 'adapter-ready';
  }

  public markTerminated(): void {
    this._phase = 'terminated';
  }

  public async startAdapterServer(
    onClientConnected: (vscodeSocket: Net.Socket, childSocket: Net.Socket) => void,
  ): Promise<number> {
    const childSocket = this._socket;
    if (!childSocket) {
      throw new Error(`Child debug session ${this._options.launcherSessionId} has no pending IPC socket`);
    }

    const adapterServer = this._createServer((vscodeSocket) => {
      adapterServer.close();
      this._adapterServer = undefined;
      onClientConnected(vscodeSocket, childSocket);
    });
    this._adapterServer = adapterServer;

    try {
      const port = await this._listenOnLoopback(adapterServer, 0);
      adapterServer.on('error', (error) => {
        this._options.onFatalError('Child debug adapter server failed', error);
      });
      return port;
    } catch (error) {
      this.dispose({ destroySocket: true });
      throw error;
    }
  }

  public dispose(options: { destroySocket: boolean }): void {
    this._phase = 'terminated';
    if (this._adapterServer) {
      this._adapterServer.close();
      this._adapterServer = undefined;
    }
    if (options.destroySocket && this._socket && !this._socket.destroyed) {
      this._socket.destroy();
    }
    this._socketPrefetchBuffer = Buffer.alloc(0);
  }

  private async _listenOnLoopback(server: Net.Server, port: number): Promise<number> {
    return await new Promise<number>((resolve, reject) => {
      const onError = (error: Error) => {
        server.off('listening', onListening);
        reject(error);
      };
      const onListening = () => {
        server.off('error', onError);
        const address = server.address();
        if (!address || typeof address === 'string') {
          reject(new Error('Failed to resolve loopback listener port'));
          return;
        }
        resolve(address.port);
      };

      server.once('error', onError);
      server.once('listening', onListening);
      server.listen(port, '127.0.0.1');
    });
  }
}