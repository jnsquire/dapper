import * as vscode from 'vscode';
import { DebugAdapterDescriptor, DebugAdapterExecutable } from 'vscode';
import { EnvironmentManager } from '../environment/EnvironmentManager.js';
import {
  type InternalChildLaunchConfiguration,
} from './debugAdapterTypes.js';
import { ChildSessionManager } from './childSessionManager.js';
import { MainSessionController } from './mainSessionController.js';
import { logger } from '../utils/logger.js';
import type { DapperLaunchHistoryService } from '../views/DapperLaunchesView.js';

export class DapperDebugAdapterDescriptorFactory implements vscode.DebugAdapterDescriptorFactory, vscode.Disposable {
  private readonly envManager: EnvironmentManager;
  private readonly extensionVersion: string;
  private readonly _mainSessionController: MainSessionController;
  private readonly _childSessionManager: ChildSessionManager;
  private readonly _disposables: vscode.Disposable;

  public constructor(
    private readonly context: vscode.ExtensionContext,
    launchHistory?: DapperLaunchHistoryService,
  ) {
    this.envManager = new EnvironmentManager(context, logger.getChannel());
    this.extensionVersion = context.extension.packageJSON.version || '0.0.0';
    this._mainSessionController = new MainSessionController(this.envManager, this.extensionVersion, launchHistory);
    this._childSessionManager = new ChildSessionManager(() => this.envManager.getOutputChannel());

    // `Disposable.from` bundles multiple disposables for easier cleanup
    this._disposables = vscode.Disposable.from(
      vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
        void this._handleDebugSessionCustomEvent(event);
      }),
      vscode.debug.onDidTerminateDebugSession((session) => {
        this._handleDebugSessionTerminated(session);
      }),
    );
  }

  // ------------------------------------------------------------------
  // Public helpers (exposed for testing or external use)
  // ------------------------------------------------------------------

  public get childSessionManager(): ChildSessionManager {
    return this._childSessionManager;
  }

  // (note: the guard is exported below, outside the class)

  private async _handleDebugSessionCustomEvent(
    event: vscode.DebugSessionCustomEvent,
  ): Promise<void> {
    if (event.session.type !== 'dapper') {
      return;
    }

    const outChannel = this.envManager.getOutputChannel();
    const body = event.body ?? {};

    try {
      switch (event.event) {
        case 'dapper/childProcess':
          await this._childSessionManager.handleChildProcessEvent(event.session, body);
          break;
        case 'dapper/childProcessExited':
          this._childSessionManager.handleChildProcessExitedEvent(body);
          break;
        case 'dapper/childProcessCandidate':
          this._childSessionManager.handleChildProcessCandidateEvent(event.session, body);
          break;
      }
    } catch (error) {
      outChannel.error(
        `Child session event handling failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  private _handleDebugSessionTerminated(session: vscode.DebugSession): void {
    if (session.type !== 'dapper') {
      return;
    }

    if (isInternalChildLaunchConfig(session.configuration)) {
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
    if (isInternalChildLaunchConfig(session.configuration)) {
      return this._childSessionManager.createChildDebugAdapterDescriptor(session, session.configuration);
    }

    const directAttachDescriptor = this._mainSessionController.createDirectAttachDescriptor(session.configuration);
    if (directAttachDescriptor) {
      return directAttachDescriptor;
    }

    // let caller log errors to avoid wrapping
    return this._mainSessionController.createDebugAdapterDescriptor(session);
  }

  public dispose(): void {
    this._disposables.dispose();
    this._childSessionManager.dispose();
    this._mainSessionController.dispose();
  }
}

// ------------------------------------------------------------------
// helpers exported for use elsewhere/tests
// ------------------------------------------------------------------

export function isInternalChildLaunchConfig(
  config: vscode.DebugConfiguration,
): config is InternalChildLaunchConfiguration {
  const candidate = config as Partial<InternalChildLaunchConfiguration>;
  return candidate.__dapperIsChildSession === true
    && typeof candidate.__dapperChildSessionId === 'string';
}
