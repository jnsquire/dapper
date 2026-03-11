import type { PendingChildSession } from './debugAdapterTypes.js';

export class ChildSessionRegistry {
  private readonly _sessionsByLauncherId = new Map<string, PendingChildSession>();
  private readonly _launcherIdsByPid = new Map<number, string>();

  public has(launcherSessionId: string): boolean {
    return this._sessionsByLauncherId.has(launcherSessionId);
  }

  public get(launcherSessionId: string): PendingChildSession | undefined {
    return this._sessionsByLauncherId.get(launcherSessionId);
  }

  public getLauncherSessionIdForPid(pid: number): string | undefined {
    return this._launcherIdsByPid.get(pid);
  }

  public register(session: PendingChildSession): void {
    this._sessionsByLauncherId.set(session.launcherSessionId, session);
    this._launcherIdsByPid.set(session.pid, session.launcherSessionId);
  }

  public unregister(launcherSessionId: string): PendingChildSession | undefined {
    const pending = this._sessionsByLauncherId.get(launcherSessionId);
    if (!pending) {
      return undefined;
    }

    this._sessionsByLauncherId.delete(launcherSessionId);
    this._launcherIdsByPid.delete(pending.pid);
    return pending;
  }

  public clearPid(pid: number): void {
    this._launcherIdsByPid.delete(pid);
  }

  public getLauncherSessionIdsForParent(parentDebugSessionId: string): string[] {
    return [...this._sessionsByLauncherId.values()]
      .filter((pending) => pending.parentDebugSessionId === parentDebugSessionId)
      .map((pending) => pending.launcherSessionId);
  }

  public getAllLauncherSessionIds(): string[] {
    return [...this._sessionsByLauncherId.keys()];
  }
}