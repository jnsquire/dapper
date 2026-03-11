import * as Net from 'net';
import { IPC_MESSAGE_KIND_COMMAND, writeIpcMessage } from './ipcMessageFraming.js';
import { logger } from '../utils/logger.js';

export interface TransportSession {
  handleTransportMessage(message: any): void;
  handleTransportClosed(exitCode: number): void;
}

export class PythonDebugAdapterTransport {
  private _pythonSocket?: Net.Socket;
  private _socketReady: Promise<Net.Socket>;
  private _resolveSocket!: (socket: Net.Socket) => void;
  private _rejectSocket!: (error: Error) => void;
  private _buffer: Buffer = Buffer.alloc(0);
  private _nextRequestId = 1;
  private readonly _pendingRequests = new Map<number, {
    resolve: (response: any) => void;
    reject: (error: Error) => void;
    timer: NodeJS.Timeout;
  }>();
  private readonly _sharedRequests = new Map<string, Promise<any>>();
  private readonly _completedSharedRequests = new Map<string, any>();
  private readonly _sessions = new Set<TransportSession>();
  private _closed = false;

  public constructor(socket?: Net.Socket, initialData?: Buffer) {
    this._socketReady = new Promise<Net.Socket>((resolve, reject) => {
      this._resolveSocket = resolve;
      this._rejectSocket = reject;
    });
    this._socketReady.catch(() => {});

    if (socket) {
      this.setPythonSocket(socket, initialData);
    }
  }

  public attachSession(session: TransportSession): void {
    this._sessions.add(session);
  }

  public detachSession(session: TransportSession): void {
    this._sessions.delete(session);
  }

  public hasAttachedSessions(): boolean {
    return this._sessions.size > 0;
  }

  public setPythonSocket(socket: Net.Socket, initialData?: Buffer): void {
    if (this._pythonSocket && this._pythonSocket !== socket) {
      this._pythonSocket.removeAllListeners('data');
      this._pythonSocket.removeAllListeners('close');
      this._pythonSocket.removeAllListeners('error');
    }

    this._pythonSocket = socket;
    this._closed = false;
    socket.on('data', (data: Buffer) => {
      this._handlePythonMessage(data);
    });
    socket.on('close', () => {
      logger.log('Python IPC socket closed');
      this._handleSocketClosed(new Error('Python IPC socket closed'));
    });
    socket.on('error', (error: Error) => {
      logger.error('Python IPC socket error', error);
    });
    if (initialData && initialData.length > 0) {
      this._handlePythonMessage(initialData);
    }
    this._resolveSocket(socket);
  }

  public async waitForSocket(timeoutMs?: number, timeoutMessage?: string): Promise<Net.Socket> {
    if (!timeoutMs || timeoutMs <= 0) {
      return this._socketReady;
    }

    return new Promise<Net.Socket>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(timeoutMessage ?? `Timed out waiting for Python IPC socket after ${timeoutMs}ms`));
      }, timeoutMs);

      this._socketReady.then((socket) => {
        clearTimeout(timer);
        resolve(socket);
      }, (error) => {
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  public async sendRequest(command: string, args: any = {}, timeoutMs: number = 30000): Promise<any> {
    const socket = await this._socketReady;
    return new Promise((resolve, reject) => {
      const requestId = this._nextRequestId++;
      logger.debug(`TS → Python: ${command} (requestId=${requestId})`);
      const timer = setTimeout(() => {
        if (this._pendingRequests.delete(requestId)) {
          const message = `[Dapper] Request ${command} (id=${requestId}) timed out after ${timeoutMs}ms`;
          logger.error(message);
          reject(new Error(message));
        }
      }, timeoutMs);

      this._pendingRequests.set(requestId, { resolve, reject, timer });

      const payloadObj: any = { command, arguments: args, id: requestId };
      writeIpcMessage(socket, payloadObj, IPC_MESSAGE_KIND_COMMAND);
    });
  }

  public async sendSharedRequest(key: string, command: string, args: any = {}, timeoutMs: number = 30000): Promise<any> {
    if (this._completedSharedRequests.has(key)) {
      return this._completedSharedRequests.get(key);
    }

    const pending = this._sharedRequests.get(key);
    if (pending) {
      return pending;
    }

    const request = this.sendRequest(command, args, timeoutMs)
      .then((result) => {
        this._completedSharedRequests.set(key, result);
        return result;
      })
      .finally(() => {
        this._sharedRequests.delete(key);
      });

    this._sharedRequests.set(key, request);
    return request;
  }

  public notifyAdapterExited(code: number): void {
    for (const session of [...this._sessions]) {
      session.handleTransportClosed(code);
    }
  }

  public dispose(): void {
    this._handleSocketClosed(new Error('Python IPC transport disposed'));
    if (this._pythonSocket && !this._pythonSocket.destroyed) {
      this._pythonSocket.destroy();
    }
    this._pythonSocket = undefined;
    this._sessions.clear();
  }

  private _handlePythonMessage(data: Buffer): void {
    this._buffer = Buffer.concat([this._buffer, data]);

    while (true) {
      if (this._buffer.length < 8) {
        return;
      }

      if (this._buffer[0] !== 0x44 || this._buffer[1] !== 0x50) {
        logger.error('Invalid magic bytes in IPC stream');
        this._buffer = Buffer.alloc(0);
        return;
      }

      const length = this._buffer.readUInt32BE(4);
      if (this._buffer.length < 8 + length) {
        return;
      }

      const payload = this._buffer.subarray(8, 8 + length);
      this._buffer = this._buffer.subarray(8 + length);

      try {
        const message = JSON.parse(payload.toString('utf8'));
        this._processPythonMessage(message);
      } catch (error) {
        logger.error('Failed to parse Python message', error);
      }
    }
  }

  private _processPythonMessage(message: any): void {
    const eventName = message.event;
    const msgJson = JSON.stringify(message);
    logger.debug(`Python → TS: ${msgJson.length > 500 ? `${msgJson.substring(0, 500)}…` : msgJson}`);

    if (eventName === 'response') {
      const msgId = message.id;
      if (msgId != null) {
        const pending = this._pendingRequests.get(msgId);
        if (pending) {
          this._pendingRequests.delete(msgId);
          clearTimeout(pending.timer);
          pending.resolve(message);
          return;
        }
        logger.warn(`Response id=${msgId} has no matching pending request (pending: ${[...this._pendingRequests.keys()]})`);
      } else if (this._pendingRequests.size > 0) {
        const firstKey = this._pendingRequests.keys().next().value!;
        const pending = this._pendingRequests.get(firstKey)!;
        this._pendingRequests.delete(firstKey);
        clearTimeout(pending.timer);
        logger.warn(`Response has no id — FIFO-matched to pending request ${firstKey}`);
        pending.resolve(message);
        return;
      } else {
        logger.warn(`Response with no id and no pending requests. Keys: ${Object.keys(message).join(', ')}`);
      }
    }

    for (const session of [...this._sessions]) {
      session.handleTransportMessage(message);
    }
  }

  private _handleSocketClosed(error: Error): void {
    if (this._closed) {
      return;
    }

    this._closed = true;
    for (const [requestId, pending] of this._pendingRequests.entries()) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this._pendingRequests.delete(requestId);
    }

    this._rejectSocket(error);
    for (const session of [...this._sessions]) {
      session.handleTransportClosed(0);
    }
  }
}