import { describe, it, expect, beforeEach, vi } from 'vitest';
import { DapperDebugSession } from '../src/debugAdapter/dapperDebugAdapter.js';
import * as Net from 'net';
import { EventEmitter } from 'events';
import { DebugProtocol } from '@vscode/debugprotocol';

// Mock LoggingDebugSession (same as existing test file, with Event added)
vi.mock('@vscode/debugadapter', () => {
    class MockLoggingDebugSession {
        protected sendResponse(response: any) { }
        protected sendEvent(event: any) { }
        public setDebuggerLinesStartAt1(val: boolean) { }
        public setDebuggerColumnsStartAt1(val: boolean) { }
        public start(inStream: any, outStream: any) { }
    }
    return {
        LoggingDebugSession: MockLoggingDebugSession,
        InitializedEvent: class { },
        TerminatedEvent: class { },
        StoppedEvent: class { constructor(public reason: string, public threadId?: number) { } },
        OutputEvent: class { constructor(public output: string, public category?: string) { } },
        Event: class { constructor(public event: string, public body?: any) { } }
    };
});

class MockSocket extends EventEmitter {
    write = vi.fn();
}

function createFrame(payload: any): Buffer {
    const json = JSON.stringify(payload);
    const len = Buffer.byteLength(json, 'utf8');
    const header = Buffer.alloc(8);
    header.write('DP', 0);
    header.writeUInt8(1, 2); // VER
    header.writeUInt8(1, 3); // KIND (1 = Event/Response)
    header.writeUInt32BE(len, 4);
    return Buffer.concat([header, Buffer.from(json, 'utf8')]);
}

describe('DapperDebugSession - Extended', () => {
    let session: DapperDebugSession;
    let mockSocket: MockSocket;

    beforeEach(() => {
        mockSocket = new MockSocket() as any;
        session = new DapperDebugSession(mockSocket as any);
        session.setPythonSocket(mockSocket as any);
    });

    // ─── formatPythonError ───────────────────────────────────────────────

    describe('formatPythonError', () => {
        it('should return "Unknown error" for null/undefined input', () => {
            expect((session as any).formatPythonError(null)).toBe('Unknown error');
            expect((session as any).formatPythonError(undefined)).toBe('Unknown error');
        });

        it('should return message when no structured details', () => {
            const result = { message: 'Something went wrong' };
            expect((session as any).formatPythonError(result)).toBe('Something went wrong');
        });

        it('should prepend error_code when present in body.details', () => {
            const result = {
                message: 'Eval failed',
                body: { details: { error_code: 'EVAL_ERROR' } }
            };
            expect((session as any).formatPythonError(result)).toBe('[EVAL_ERROR] Eval failed');
        });

        it('should append cause when present in body.details', () => {
            const result = {
                message: 'Eval failed',
                body: { details: { cause: 'NameError' } }
            };
            expect((session as any).formatPythonError(result)).toBe('Eval failed (caused by: NameError)');
        });

        it('should handle error_code and cause together', () => {
            const result = {
                message: 'Eval failed',
                body: { details: { error_code: 'EVAL_ERROR', cause: 'NameError' } }
            };
            expect((session as any).formatPythonError(result)).toBe(
                '[EVAL_ERROR] Eval failed (caused by: NameError)'
            );
        });
    });

    // ─── handleGeneralEvent - new event types ────────────────────────────

    describe('handleGeneralEvent - new event types', () => {
        it('should forward dapper/log events as OutputEvent', () => {
            const sendEventSpy = vi.spyOn(session as any, 'sendEvent');

            const payload = {
                event: 'dapper/log',
                body: { message: 'test log', category: 'console', level: 'info' }
            };
            mockSocket.emit('data', createFrame(payload));

            expect(sendEventSpy).toHaveBeenCalledTimes(1);
            expect(sendEventSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    output: 'test log',
                    category: 'console'
                })
            );
        });

        it('should forward dapper/telemetry events as custom Event', () => {
            const sendEventSpy = vi.spyOn(session as any, 'sendEvent');

            const payload = {
                event: 'dapper/telemetry',
                body: { snapshot: { counter: 1 } }
            };
            mockSocket.emit('data', createFrame(payload));

            expect(sendEventSpy).toHaveBeenCalledTimes(1);
            expect(sendEventSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    event: 'dapper/telemetry',
                    body: { snapshot: { counter: 1 } }
                })
            );
        });
    });

    // ─── setExpressionRequest ────────────────────────────────────────────

    describe('setExpressionRequest', () => {
        it('should forward setExpression to Python and return result', async () => {
            const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');

            const response: DebugProtocol.SetExpressionResponse = {
                seq: 0,
                type: 'response',
                request_seq: 10,
                command: 'setExpression',
                success: true,
                body: { value: '' }
            };

            const promise = (session as any).setExpressionRequest(
                response,
                { expression: 'x', value: '42', frameId: 1 }
            );

            // Extract request ID from the sent frame
            expect(mockSocket.write).toHaveBeenCalled();
            const sentData = mockSocket.write.mock.calls[0][0] as Buffer;
            const sentJson = JSON.parse(sentData.subarray(8).toString('utf8'));
            expect(sentJson.command).toBe('setExpression');
            const requestId = sentJson.id;

            // Simulate success response from Python
            mockSocket.emit('data', createFrame({
                event: 'response',
                id: requestId,
                success: true,
                body: { value: '42', type: 'int' }
            }));

            await promise;

            expect(sendResponseSpy).toHaveBeenCalled();
            const sent = sendResponseSpy.mock.calls[0][0] as DebugProtocol.SetExpressionResponse;
            expect(sent.body.value).toBe('42');
            expect(sent.body.type).toBe('int');
        });

        it('should handle error response from Python', async () => {
            const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');

            const response: DebugProtocol.SetExpressionResponse = {
                seq: 0,
                type: 'response',
                request_seq: 11,
                command: 'setExpression',
                success: true,
                body: { value: '' }
            };

            const promise = (session as any).setExpressionRequest(
                response,
                { expression: 'x', value: '42', frameId: 1 }
            );

            const sentData = mockSocket.write.mock.calls[0][0] as Buffer;
            const sentJson = JSON.parse(sentData.subarray(8).toString('utf8'));
            const requestId = sentJson.id;

            // Simulate failure response from Python
            mockSocket.emit('data', createFrame({
                event: 'response',
                id: requestId,
                success: false,
                message: 'Failed',
                body: { details: { error_code: 'EVAL_ERROR' } }
            }));

            await promise;

            expect(sendResponseSpy).toHaveBeenCalled();
            const sent = sendResponseSpy.mock.calls[0][0] as DebugProtocol.SetExpressionResponse;
            expect(sent.success).toBe(false);
            expect(sent.message).toContain('EVAL_ERROR');
        });
    });

    // ─── stepInTargetsRequest ────────────────────────────────────────────

    describe('stepInTargetsRequest', () => {
        it('should forward stepInTargets to Python and return targets', async () => {
            const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');

            const response: DebugProtocol.StepInTargetsResponse = {
                seq: 0,
                type: 'response',
                request_seq: 20,
                command: 'stepInTargets',
                success: true,
                body: { targets: [] }
            };

            const promise = (session as any).stepInTargetsRequest(
                response,
                { frameId: 1 }
            );

            expect(mockSocket.write).toHaveBeenCalled();
            const sentData = mockSocket.write.mock.calls[0][0] as Buffer;
            const sentJson = JSON.parse(sentData.subarray(8).toString('utf8'));
            expect(sentJson.command).toBe('stepInTargets');
            const requestId = sentJson.id;

            mockSocket.emit('data', createFrame({
                event: 'response',
                id: requestId,
                success: true,
                body: { targets: [{ id: 0, label: 'foo' }] }
            }));

            await promise;

            expect(sendResponseSpy).toHaveBeenCalled();
            const sent = sendResponseSpy.mock.calls[0][0] as DebugProtocol.StepInTargetsResponse;
            expect(sent.body.targets).toHaveLength(1);
            expect(sent.body.targets[0]).toEqual({ id: 0, label: 'foo' });
        });
    });

    // ─── customRequest ──────────────────────────────────────────────────

    describe('customRequest', () => {
        it('should forward dapper/* custom requests to Python', async () => {
            const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');

            const response: DebugProtocol.Response = {
                seq: 0,
                type: 'response',
                request_seq: 30,
                command: 'dapper/hotReload',
                success: true,
                body: {}
            };

            const promise = (session as any).customRequest(
                'dapper/hotReload',
                response,
                { file: 'main.py' }
            );

            expect(mockSocket.write).toHaveBeenCalled();
            const sentData = mockSocket.write.mock.calls[0][0] as Buffer;
            const sentJson = JSON.parse(sentData.subarray(8).toString('utf8'));
            expect(sentJson.command).toBe('dapper/hotReload');
            const requestId = sentJson.id;

            mockSocket.emit('data', createFrame({
                event: 'response',
                id: requestId,
                success: true,
                body: { reloaded: true }
            }));

            await promise;

            expect(sendResponseSpy).toHaveBeenCalled();
            const sent = sendResponseSpy.mock.calls[0][0] as DebugProtocol.Response;
            expect(sent.success).not.toBe(false);
            expect(sent.body).toEqual({ reloaded: true });
        });

        it('should reject non-dapper custom requests', async () => {
            const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');

            const response: DebugProtocol.Response = {
                seq: 0,
                type: 'response',
                request_seq: 31,
                command: 'unknown/thing',
                success: true,
                body: {}
            };

            await (session as any).customRequest(
                'unknown/thing',
                response,
                {}
            );

            expect(sendResponseSpy).toHaveBeenCalled();
            const sent = sendResponseSpy.mock.calls[0][0] as DebugProtocol.Response;
            expect(sent.success).toBe(false);
            expect(sent.message).toContain('Unrecognized custom request');
        });
    });
});
