import * as vscode from 'vscode';
import { DebugAdapterDescriptor, DebugAdapterExecutable } from 'vscode';
import { EnvironmentManager } from '../environment/EnvironmentManager.js';
import {
  type InternalChildLaunchConfiguration,
} from './debugAdapterTypes.js';
import { ChildSessionManager } from './childSessionManager.js';
import { MainSessionController } from './mainSessionController.js';
import { logger } from '../utils/logger.js';

export class DapperDebugAdapterDescriptorFactory implements vscode.DebugAdapterDescriptorFactory, vscode.Disposable {
  private readonly envManager: EnvironmentManager;
  private readonly extensionVersion: string;
  private readonly _mainSessionController: MainSessionController;
  private readonly _childSessionManager: ChildSessionManager;
  private readonly _disposables: vscode.Disposable[] = [];

  public constructor(private readonly context: vscode.ExtensionContext) {
    this.envManager = new EnvironmentManager(context, logger.getChannel());
    this.extensionVersion = context.extension.packageJSON.version || '0.0.0';
    this._mainSessionController = new MainSessionController(this.envManager, this.extensionVersion);
    this._childSessionManager = new ChildSessionManager(() => this.envManager.getOutputChannel());
    this._disposables.push(
      vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
        void this._handleDebugSessionCustomEvent(event);
      }),
      vscode.debug.onDidTerminateDebugSession((session) => {
        this._handleDebugSessionTerminated(session);
      }),
    );
  }

  private get _childSessions() {
    return this._childSessionManager.childSessions;
  }

  private get _childSessionIdsByPid() {
    return this._childSessionManager.childSessionIdsByPid;
  }

  private _isInternalChildLaunchConfig(
    config: vscode.DebugConfiguration,
  ): config is InternalChildLaunchConfiguration {
    const candidate = config as Partial<InternalChildLaunchConfiguration>;
    return candidate.__dapperIsChildSession === true
      && typeof candidate.__dapperChildSessionId === 'string';
  }

  private async _handleDebugSessionCustomEvent(
    event: vscode.DebugSessionCustomEvent,
  ): Promise<void> {
    if (event.session.type !== 'dapper') {
      return;
    }

    try {
      if (event.event === 'dapper/childProcess') {
        await this._childSessionManager.handleChildProcessEvent(event.session, event.body ?? {});
      } else if (event.event === 'dapper/childProcessExited') {
        this._childSessionManager.handleChildProcessExitedEvent(event.body ?? {});
      } else if (event.event === 'dapper/childProcessCandidate') {
        this._childSessionManager.handleChildProcessCandidateEvent(event.session, event.body ?? {});
      }
    } catch (error) {
      this.envManager.getOutputChannel().error(
        `Child session event handling failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  private _handleDebugSessionTerminated(session: vscode.DebugSession): void {
    if (session.type !== 'dapper') {
      return;
    }

    if (this._isInternalChildLaunchConfig(session.configuration)) {
      this._childSessionManager.disposePendingChildSession(
        session.configuration.__dapperChildSessionId,
        { destroySocket: true },
      );
      return;
    }

    if (!this._mainSessionController.removeSessionId(session.id)) {
      return;
    }

    this._childSessionManager.handleParentSessionTerminated(session);
    this._mainSessionController.reset();
  }

  public async createDebugAdapterDescriptor(
    session: vscode.DebugSession,
    _executable: DebugAdapterExecutable | undefined,
  ): Promise<DebugAdapterDescriptor> {
    if (this._isInternalChildLaunchConfig(session.configuration)) {
      return this._childSessionManager.createChildDebugAdapterDescriptor(session, session.configuration);
    }

    const directAttachDescriptor = this._mainSessionController.createDirectAttachDescriptor(session.configuration);
    if (directAttachDescriptor) {
      return directAttachDescriptor;
    }

    try {
      return await this._mainSessionController.createDebugAdapterDescriptor(session);
    } catch (error) {
      logger.error('Error creating debug adapter', error);
      throw error;
    }
  }

  public dispose(): void {
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
    this._childSessionManager.dispose();
    this._mainSessionController.dispose();
  }
}
