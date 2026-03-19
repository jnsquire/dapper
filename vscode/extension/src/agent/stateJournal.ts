/**
 * StateJournal: Passive DAP event recorder implementing DebugAdapterTracker.
 *
 * Intercepts DAP messages flowing between VS Code and the Dapper adapter,
 * recording state snapshots on stop events and enabling efficient diff queries
 * so agents can observe "what changed" without re-fetching full state.
 */

import * as vscode from 'vscode';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VariableSnapshot {
  [name: string]: string;
}

export interface FrameSummary {
  name: string;
  file: string;
  line: number;
  locals?: VariableSnapshot;
}

export interface DebugSnapshot {
  checkpoint: number;
  timestamp: number;
  stopReason: string;
  threadId: number;
  location: string;
  callStack: FrameSummary[];
  locals: VariableSnapshot;
  globals: VariableSnapshot;
  stoppedThreads: number[];
  runningThreads: number[];
}

export interface JournalEntry {
  checkpoint: number;
  timestamp: number;
  type: 'stopped' | 'continued' | 'thread' | 'breakpoint' | 'output' | 'terminated';
  summary: string;
  snapshot?: DebugSnapshot;
}

export interface VariableChange {
  old: string;
  new: string;
}

export interface StateDiff {
  fromCheckpoint: number;
  toCheckpoint: number;
  stopReason?: string;
  locationChanged?: string;
  variableChanges: {
    added: VariableSnapshot;
    changed: { [name: string]: VariableChange };
    removed: string[];
  };
  newOutput: string;
  entries: JournalEntry[];
}

export interface BreakpointVerificationRecord {
  verified?: boolean;
  verificationState: 'verified' | 'pending' | 'rejected';
  verificationMessage?: string;
}

export interface BreakpointVerificationSummary extends BreakpointVerificationRecord {
  file: string;
  line: number;
}

export interface BreakpointStatusCounts {
  verified: number;
  pending: number;
  rejected: number;
}

export type SessionLifecycleState =
  | 'initializing'
  | 'waiting-for-breakpoints'
  | 'ready'
  | 'running'
  | 'stopped'
  | 'error'
  | 'unknown';

export interface SessionTransitionRecord {
  state: SessionLifecycleState;
  reason: string;
  timestamp: number;
}

export interface SessionReadinessInfo {
  lifecycleState: SessionLifecycleState;
  breakpointRegistrationComplete: boolean;
  lastTransition: SessionTransitionRecord;
  lastError?: string;
}

// ---------------------------------------------------------------------------
// Ring buffer
// ---------------------------------------------------------------------------

class RingBuffer<T> {
  private buffer: (T | undefined)[];
  private head = 0;
  private count = 0;

  constructor(private capacity: number) {
    this.buffer = new Array(capacity);
  }

  push(item: T): void {
    this.buffer[this.head] = item;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) {
      this.count++;
    }
  }

  toArray(): T[] {
    if (this.count === 0) return [];
    const result: T[] = [];
    const start = this.count < this.capacity ? 0 : this.head;
    for (let i = 0; i < this.count; i++) {
      result.push(this.buffer[(start + i) % this.capacity] as T);
    }
    return result;
  }

  last(): T | undefined {
    if (this.count === 0) return undefined;
    return this.buffer[(this.head - 1 + this.capacity) % this.capacity];
  }

  get size(): number {
    return this.count;
  }
}

// ---------------------------------------------------------------------------
// StateJournal
// ---------------------------------------------------------------------------

const DEFAULT_MAX_ENTRIES = 200;
const MIN_HISTORY_ENTRIES = 10;
const MAX_HISTORY_ENTRIES = 5000;
const MAX_OUTPUT_LINES = 50;

export class StateJournal implements vscode.DebugAdapterTracker {
  private _checkpoint = 0;
  private _entries: RingBuffer<JournalEntry>;
  private _outputBuffer: string[] = [];
  private _lastSnapshot: DebugSnapshot | undefined;
  private _breakpointVerification = new Map<string, BreakpointVerificationRecord>();
  private _session: vscode.DebugSession;
  private _disposed = false;
  private _lastTransition: SessionTransitionRecord = {
    state: 'initializing',
    reason: 'Debug session created',
    timestamp: Date.now(),
  };

  private _lastError: string | undefined;

  constructor(session: vscode.DebugSession) {
    this._session = session;
    this._entries = new RingBuffer<JournalEntry>(getHistoryEntryCapacity());
  }

  // -- DebugAdapterTracker implementation ----------------------------------

  onDidSendMessage(message: Record<string, unknown>): void {
    if (this._disposed) return;

    const type = message['type'];
    if (type !== 'event') return;

    const event = message['event'] as string;
    const body = (message['body'] as Record<string, unknown>) ?? {};

    switch (event) {
      case 'initialized':
        this._setLifecycleState(
          this._isBreakpointRegistrationComplete() ? 'ready' : 'waiting-for-breakpoints',
          'Adapter finished initialize handshake',
        );
        break;
      case 'stopped':
        this._onStopped(body);
        break;
      case 'continued':
        this._setLifecycleState('running', `Thread ${body['threadId'] ?? '?'} continued`);
        this._recordEntry('continued', `Thread ${body['threadId'] ?? '?'} continued`);
        break;
      case 'thread':
        this._recordEntry('thread', `Thread ${body['threadId'] ?? '?'} ${body['reason'] ?? 'event'}`);
        break;
      case 'breakpoint':
        this._updateBreakpointFromEvent(body);
        this._recordEntry('breakpoint', `Breakpoint ${body['reason'] ?? 'changed'}`);
        break;
      case 'output': {
        const text = (body['output'] as string) ?? '';
        if (text) {
          this._outputBuffer.push(text);
          if (this._outputBuffer.length > MAX_OUTPUT_LINES) {
            this._outputBuffer.shift();
          }
        }
        this._recordEntry('output', text.slice(0, 120));
        break;
      }
      case 'terminated':
        this._setLifecycleState('unknown', 'Debug session terminated');
        this._recordEntry('terminated', 'Debug session terminated');
        break;
    }
  }

  onWillStopSession(): void {
    this._disposed = true;
  }

  // -- Public API for tools ------------------------------------------------

  get checkpoint(): number {
    return this._checkpoint;
  }

  get lastSnapshot(): DebugSnapshot | undefined {
    return this._lastSnapshot;
  }

  get sessionId(): string {
    return this._session.id;
  }

  get session(): vscode.DebugSession {
    return this._session;
  }

  getBreakpointVerification(file: string, line: number): BreakpointVerificationRecord | undefined {
    return this._breakpointVerification.get(this._breakpointKey(file, line));
  }

  getBreakpointVerifications(): BreakpointVerificationSummary[] {
    return Array.from(this._breakpointVerification.entries())
      .map(([key, record]) => {
        const separator = key.lastIndexOf(':');
        const file = separator >= 0 ? key.slice(0, separator) : key;
        const line = separator >= 0 ? Number(key.slice(separator + 1)) : Number.NaN;
        return {
          file,
          line,
          ...record,
        };
      })
      .filter((entry) => Number.isFinite(entry.line));
  }

  getBreakpointStatusCounts(): BreakpointStatusCounts {
    const counts: BreakpointStatusCounts = {
      verified: 0,
      pending: 0,
      rejected: 0,
    };

    for (const record of this._breakpointVerification.values()) {
      counts[record.verificationState]++;
    }

    return counts;
  }

  updateBreakpointVerification(
    file: string,
    line: number,
    record: BreakpointVerificationRecord,
  ): void {
    this._breakpointVerification.set(this._breakpointKey(file, line), record);
    this._refreshBreakpointRegistrationState(`Breakpoint verification updated for ${file}:${line}`);
  }

  clearBreakpointVerifications(file?: string): void {
    if (!file) {
      this._breakpointVerification.clear();
      this._refreshBreakpointRegistrationState('Cleared cached breakpoint verifications');
      return;
    }

    const prefix = `${normalizeBreakpointPath(file)}:`;
    for (const key of this._breakpointVerification.keys()) {
      if (key.startsWith(prefix)) {
        this._breakpointVerification.delete(key);
      }
    }
    this._refreshBreakpointRegistrationState(`Cleared cached breakpoint verifications for ${file}`);
  }

  deleteBreakpointVerification(file: string, line: number): void {
    this._breakpointVerification.delete(this._breakpointKey(file, line));
    this._refreshBreakpointRegistrationState(`Deleted cached breakpoint verification for ${file}:${line}`);
  }

  /**
   * Build a snapshot by sending a custom request to the adapter.
   * Falls back to the cached last snapshot on failure.
   */
  async getSnapshot(threadId?: number): Promise<DebugSnapshot | undefined> {
    try {
      const snap = await this._requestSnapshot({
        threadId,
        checkpoint: this._checkpoint,
        timestamp: Date.now(),
      });
      if (snap) {
        this._lastSnapshot = snap;
        this._lastError = undefined;
        return snap;
      }
    } catch (err: unknown) {
      this._setLifecycleState('error', 'Failed to retrieve debug snapshot', err instanceof Error ? err.message : String(err));
    }
    return this._lastSnapshot;
  }

  /**
   * Return the last error from getSnapshot(), if any.
   */
  get lastError(): string | undefined {
    return this._lastError;
  }

  get readinessInfo(): SessionReadinessInfo {
    return {
      lifecycleState: this._lastTransition.state,
      breakpointRegistrationComplete: this._isBreakpointRegistrationComplete(),
      lastTransition: { ...this._lastTransition },
      lastError: this._lastError,
    };
  }

  /**
   * Compute what changed between a previous checkpoint and now.
   */
  getDiffSince(sinceCheckpoint: number): StateDiff {
    const entries = this._entries.toArray().filter(e => e.checkpoint > sinceCheckpoint);

    const current = this._lastSnapshot;
    const previous = entries.find(e => e.snapshot)?.snapshot;

    const diff: StateDiff = {
      fromCheckpoint: sinceCheckpoint,
      toCheckpoint: this._checkpoint,
      stopReason: current?.stopReason,
      variableChanges: { added: {}, changed: {}, removed: [] },
      newOutput: this._outputBuffer.join(''),
      entries,
    };

    if (current && previous) {
      diff.locationChanged = previous.location !== current.location
        ? `${previous.location} → ${current.location}`
        : undefined;

      // Compute variable diffs
      const prevLocals = previous.locals;
      const currLocals = current.locals;

      for (const [name, value] of Object.entries(currLocals)) {
        if (!(name in prevLocals)) {
          diff.variableChanges.added[name] = value;
        } else if (prevLocals[name] !== value) {
          diff.variableChanges.changed[name] = {
            old: prevLocals[name],
            new: value,
          };
        }
      }
      for (const name of Object.keys(prevLocals)) {
        if (!(name in currLocals)) {
          diff.variableChanges.removed.push(name);
        }
      }
    }

    return diff;
  }

  /**
   * Return the most recent N journal entries.
   */
  getRecentHistory(count: number): JournalEntry[] {
    const all = this._entries.toArray();
    return all.slice(-count);
  }

  // -- Private helpers -----------------------------------------------------

  private _onStopped(body: Record<string, unknown>): void {
    const threadId = (body['threadId'] as number) ?? 0;
    const reason = (body['reason'] as string) ?? 'breakpoint';

    this._setLifecycleState('stopped', `Stopped: ${reason} on thread ${threadId}`);

    const entry = this._recordEntry('stopped', `Stopped: ${reason} on thread ${threadId}`);

    // Snapshot capture happens asynchronously; the last snapshot will be
    // updated when getSnapshot() is called by a tool.  We store a minimal
    // placeholder here so diff detection has a checkpoint reference.
    const placeholder: DebugSnapshot = {
      checkpoint: entry.checkpoint,
      timestamp: entry.timestamp,
      stopReason: reason,
      threadId,
      location: '',
      callStack: [],
      locals: {},
      globals: {},
      stoppedThreads: [threadId],
      runningThreads: [],
    };
    entry.snapshot = placeholder;
    this._lastSnapshot = placeholder;
    void this._captureSnapshotForEntry(entry, threadId, reason);
  }

  private async _captureSnapshotForEntry(
    entry: JournalEntry,
    threadId: number,
    stopReason: string,
  ): Promise<void> {
    const snapshot = await this._requestSnapshot({
      threadId,
      checkpoint: entry.checkpoint,
      timestamp: entry.timestamp,
      fallbackStopReason: stopReason,
    });
    if (!snapshot || this._disposed) {
      return;
    }

    entry.snapshot = snapshot;
    if (!this._lastSnapshot || this._lastSnapshot.checkpoint <= entry.checkpoint) {
      this._lastSnapshot = snapshot;
    }
    this._lastError = undefined;
    this._setLifecycleState('stopped', `Captured snapshot for stopped thread ${threadId}`);
  }

  private async _requestSnapshot(options: {
    threadId?: number;
    checkpoint: number;
    timestamp: number;
    fallbackStopReason?: string;
  }): Promise<DebugSnapshot | undefined> {
    const args: Record<string, unknown> = {};
    if (options.threadId !== undefined) {
      args['threadId'] = options.threadId;
    }

    const result = await this._session.customRequest('dapper/agentSnapshot', args);
    if (!result) {
      return undefined;
    }

    const selectedThreadId = typeof result.threadId === 'number'
      ? result.threadId
      : options.threadId ?? result.stoppedThreads?.[0] ?? 0;
    return {
      checkpoint: options.checkpoint,
      timestamp: options.timestamp,
      stopReason: result.stopReason ?? options.fallbackStopReason ?? 'unknown',
      threadId: selectedThreadId,
      location: result.location ?? '<unknown>',
      callStack: result.callStack ?? [],
      locals: result.locals ?? {},
      globals: result.globals ?? {},
      stoppedThreads: result.stoppedThreads ?? [],
      runningThreads: result.runningThreads ?? [],
    };
  }

  private _recordEntry(
    type: JournalEntry['type'],
    summary: string,
  ): JournalEntry {
    this._checkpoint++;
    const entry: JournalEntry = {
      checkpoint: this._checkpoint,
      timestamp: Date.now(),
      type,
      summary,
    };
    this._entries.push(entry);
    return entry;
  }

  private _updateBreakpointFromEvent(body: Record<string, unknown>): void {
    const breakpoint = (body['breakpoint'] as Record<string, unknown> | undefined) ?? {};
    const source = (breakpoint['source'] as Record<string, unknown> | undefined) ?? {};
    const file = typeof source['path'] === 'string' ? source['path'] : undefined;
    const line = typeof breakpoint['line'] === 'number' ? breakpoint['line'] : undefined;
    if (!file || line === undefined) {
      return;
    }

    const verified = breakpoint['verified'];
    const message = typeof breakpoint['message'] === 'string'
      ? breakpoint['message']
      : undefined;
    const record = toBreakpointVerificationRecord(verified, message);
    if (record) {
      this.updateBreakpointVerification(file, line, record);
    }
  }

  private _refreshBreakpointRegistrationState(reason: string): void {
    const hasPendingBreakpoints = this._hasPendingBreakpointVerifications();

    if (hasPendingBreakpoints) {
      this._setLifecycleState('waiting-for-breakpoints', reason);
      return;
    }

    if (this._lastTransition.state === 'initializing' || this._lastTransition.state === 'waiting-for-breakpoints') {
      this._setLifecycleState('ready', reason);
    }
  }

  private _setLifecycleState(state: SessionLifecycleState, reason: string, error?: string): void {
    this._lastTransition = {
      state,
      reason,
      timestamp: Date.now(),
    };

    if (error !== undefined) {
      this._lastError = error;
    } else if (state !== 'error') {
      this._lastError = undefined;
    }
  }

  private _isBreakpointRegistrationComplete(): boolean {
    if (this._lastTransition.state === 'initializing') {
      return false;
    }

    return !this._hasPendingBreakpointVerifications();
  }

  private _hasPendingBreakpointVerifications(): boolean {
    return Array.from(this._breakpointVerification.values())
      .some((record) => record.verificationState === 'pending');
  }

  private _breakpointKey(file: string, line: number): string {
    return `${normalizeBreakpointPath(file)}:${line}`;
  }
}

function normalizeBreakpointPath(file: string): string {
  return process.platform === 'win32' ? file.toLowerCase() : file;
}

function getHistoryEntryCapacity(): number {
  const configured = vscode.workspace
    .getConfiguration('dapper')
    .get<number>('agent.executionHistorySize', DEFAULT_MAX_ENTRIES);
  return clampHistoryEntryCapacity(configured ?? DEFAULT_MAX_ENTRIES);
}

function clampHistoryEntryCapacity(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_MAX_ENTRIES;
  }

  const rounded = Math.trunc(value);
  return Math.min(MAX_HISTORY_ENTRIES, Math.max(MIN_HISTORY_ENTRIES, rounded));
}

function createBreakpointVerificationRecord(
  verificationState: BreakpointVerificationRecord['verificationState'],
  verified?: boolean,
  verificationMessage?: string,
): BreakpointVerificationRecord {
  return {
    verificationState,
    ...(verified !== undefined ? { verified } : {}),
    ...(verificationMessage !== undefined
      ? { verificationMessage }
      : {}),
  };
}

export function toBreakpointVerificationRecord(
  verified: unknown,
  message?: string,
): BreakpointVerificationRecord | undefined {
  if (verified === true) {
    return createBreakpointVerificationRecord('verified', true, message);
  }
  if (verified === false) {
    return createBreakpointVerificationRecord(
      message ? 'rejected' : 'pending',
      message ? false : undefined,
      message,
    );
  }
  if (message) {
    return createBreakpointVerificationRecord('rejected', false, message);
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Journal Registry — maps session IDs to journals
// ---------------------------------------------------------------------------

export class JournalRegistry implements vscode.Disposable {
  private _journals = new Map<string, StateJournal>();
  private _disposables: vscode.Disposable[] = [];

  constructor() {
    this._disposables.push(
      vscode.debug.onDidTerminateDebugSession((session) => {
        this._journals.delete(session.id);
      }),
    );
  }

  /**
   * Get or create a journal for the given session.
   */
  getOrCreate(session: vscode.DebugSession): StateJournal {
    let journal = this._journals.get(session.id);
    if (!journal) {
      journal = new StateJournal(session);
      this._journals.set(session.id, journal);
    }
    return journal;
  }

  /**
   * Get the journal for a specific session, or the active dapper session.
   */
  resolve(sessionId?: string): StateJournal | undefined {
    if (sessionId) {
      return this._journals.get(sessionId);
    }
    // Default to active dapper session
    const active = vscode.debug.activeDebugSession;
    if (active?.type === 'dapper') {
      return this._journals.get(active.id);
    }
    // Return first available
    for (const journal of this._journals.values()) {
      return journal;
    }
    return undefined;
  }

  get journals(): ReadonlyMap<string, StateJournal> {
    return this._journals;
  }

  dispose(): void {
    this._disposables.forEach(d => d.dispose());
    this._journals.clear();
  }
}

// ---------------------------------------------------------------------------
// DebugAdapterTrackerFactory
// ---------------------------------------------------------------------------

export class DapperTrackerFactory implements vscode.DebugAdapterTrackerFactory {
  constructor(private _registry: JournalRegistry) {}

  createDebugAdapterTracker(session: vscode.DebugSession): vscode.ProviderResult<vscode.DebugAdapterTracker> {
    if (session.type !== 'dapper') return undefined;
    return this._registry.getOrCreate(session);
  }
}
