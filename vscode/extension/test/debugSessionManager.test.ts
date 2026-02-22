import { describe, it, expect, vi, beforeEach } from 'vitest';

// Grab the vscode mock so we can extend it with event handlers
const vscode = await import('vscode');

let startHandler: ((session: any) => void) | null = null;
let terminateHandler: ((session: any) => void) | null = null;
let customEventHandler: ((event: any) => void) | null = null;

const startDispose = vi.fn();
const terminateDispose = vi.fn();
const customEventDispose = vi.fn();

(vscode.debug as any).onDidStartDebugSession = vi.fn((handler: any, thisArg?: any) => {
    startHandler = thisArg ? handler.bind(thisArg) : handler;
    return { dispose: startDispose };
});
(vscode.debug as any).onDidTerminateDebugSession = vi.fn((handler: any, thisArg?: any) => {
    terminateHandler = thisArg ? handler.bind(thisArg) : handler;
    return { dispose: terminateDispose };
});
(vscode.debug as any).onDidReceiveDebugSessionCustomEvent = vi.fn((handler: any, thisArg?: any) => {
    customEventHandler = thisArg ? handler.bind(thisArg) : handler;
    return { dispose: customEventDispose };
});

// Spy on window methods
vi.spyOn(vscode.window, 'showWarningMessage');
vi.spyOn(vscode.window, 'showErrorMessage');

const { DebugSessionManager } = await import('../src/debugAdapter/debugSessionManager.js');

function makeDapperSession(id: string) {
    return { type: 'dapper', id, name: `session-${id}` };
}

function makeNonDapperSession(id: string) {
    return { type: 'python', id, name: `python-${id}` };
}

describe('DebugSessionManager', () => {
    let manager: InstanceType<typeof DebugSessionManager>;

    beforeEach(() => {
        vi.clearAllMocks();
        startHandler = null;
        terminateHandler = null;
        customEventHandler = null;
        manager = new DebugSessionManager();
    });

    describe('session tracking', () => {
        it('should track dapper sessions when they start', () => {
            const session = makeDapperSession('s1');
            startHandler!(session);

            expect(manager.getSession('s1')).toBe(session);
        });

        it('should ignore non-dapper sessions', () => {
            const session = makeNonDapperSession('s1');
            startHandler!(session);

            expect(manager.getSession('s1')).toBeUndefined();
        });

        it('should remove sessions when they terminate', () => {
            const session = makeDapperSession('s1');
            startHandler!(session);
            expect(manager.getSession('s1')).toBe(session);

            terminateHandler!(session);
            expect(manager.getSession('s1')).toBeUndefined();
        });

        it('should track multiple sessions', () => {
            const s1 = makeDapperSession('s1');
            const s2 = makeDapperSession('s2');
            startHandler!(s1);
            startHandler!(s2);

            expect(manager.getSession('s1')).toBe(s1);
            expect(manager.getSession('s2')).toBe(s2);
        });
    });

    describe('stopped state tracking', () => {
        it('should mark session as stopped on stopped event', () => {
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'stopped',
            });

            expect(manager.isSessionStopped('s1')).toBe(true);
        });

        it('should clear stopped state on continued event', () => {
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'stopped',
            });
            expect(manager.isSessionStopped('s1')).toBe(true);

            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'continued',
            });
            expect(manager.isSessionStopped('s1')).toBe(false);
        });

        it('should clear stopped state on terminated event', () => {
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'stopped',
            });
            expect(manager.isSessionStopped('s1')).toBe(true);

            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'terminated',
            });
            expect(manager.isSessionStopped('s1')).toBe(false);
        });

        it('should not track stopped state for non-dapper sessions', () => {
            customEventHandler!({
                session: { type: 'python', id: 's1' },
                event: 'stopped',
            });

            expect(manager.isSessionStopped('s1')).toBe(false);
        });
    });

    describe('hot reload warnings', () => {
        it('should show warning message for hot reload with warnings', () => {
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'dapper/hotReloadResult',
                body: { warnings: ['closure skipped'] },
            });

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'Dapper hot reload warnings: closure skipped'
            );
        });

        it('should not show warning when no warnings', () => {
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'dapper/hotReloadResult',
                body: { warnings: [] },
            });

            expect(vscode.window.showWarningMessage).not.toHaveBeenCalled();
        });
    });

    describe('startDebugging', () => {
        it('should call vscode.debug.startDebugging with correct config', async () => {
            (vscode.debug.startDebugging as any) = vi.fn().mockResolvedValue(true);

            const result = await manager.startDebugging('mySession', {
                type: 'dapper',
                name: 'test',
                request: 'launch',
                program: 'app.py',
            });

            expect(result).toBe(true);
            expect(vscode.debug.startDebugging).toHaveBeenCalledWith(undefined, {
                type: 'dapper',
                name: 'mySession',
                request: 'launch',
                program: 'app.py',
            });
        });

        it('should show error message when startDebugging throws', async () => {
            (vscode.debug.startDebugging as any) = vi.fn().mockRejectedValue(
                new Error('connection refused')
            );

            const result = await manager.startDebugging('mySession', {
                type: 'dapper',
                name: 'test',
                request: 'launch',
            });

            expect(result).toBe(false);
            expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
                'Failed to start debugging: connection refused'
            );
        });
    });

    describe('dispose', () => {
        it('should clear sessions and stopped sets', () => {
            startHandler!(makeDapperSession('s1'));
            customEventHandler!({
                session: { type: 'dapper', id: 's1' },
                event: 'stopped',
            });

            expect(manager.getSession('s1')).toBeDefined();
            expect(manager.isSessionStopped('s1')).toBe(true);

            manager.dispose();

            expect(manager.getSession('s1')).toBeUndefined();
            expect(manager.isSessionStopped('s1')).toBe(false);
        });

        it('should dispose all registered event handlers', () => {
            manager.dispose();

            expect(startDispose).toHaveBeenCalled();
            expect(terminateDispose).toHaveBeenCalled();
            expect(customEventDispose).toHaveBeenCalled();
        });
    });
});
