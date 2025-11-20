
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { DapperDebugSession } from '../src/debugAdapter/dapperDebugAdapter.js';
import * as Net from 'net';
import { EventEmitter } from 'events';
import { DebugProtocol } from '@vscode/debugprotocol';

// Mock LoggingDebugSession
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
        OutputEvent: class { constructor(public output: string, public category?: string) { } }
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

describe('DapperDebugSession', () => {
    let session: DapperDebugSession;
    let mockSocket: MockSocket;

    beforeEach(() => {
        mockSocket = new MockSocket() as any;
        session = new DapperDebugSession(mockSocket as any);
        // Manually call setPythonSocket to attach the 'data' listener to the mock socket.
        // The constructor sets the property but does not attach listeners; that is normally done by the adapter factory.
        session.setPythonSocket(mockSocket as any);
    });

    it('should parse complete messages from Python', () => {
        const payload = { event: 'output', output: 'hello', category: 'console' };
        const frame = createFrame(payload);
        
        const sendEventSpy = vi.spyOn(session as any, 'sendEvent');
        
        mockSocket.emit('data', frame);
        
        expect(sendEventSpy).toHaveBeenCalledWith(expect.objectContaining({
            output: 'hello',
            category: 'console'
        }));
    });

    it('should handle split messages (chunked data)', () => {
        const payload = { event: 'output', output: 'split', category: 'console' };
        const frame = createFrame(payload);
        
        const part1 = frame.subarray(0, 5);
        const part2 = frame.subarray(5);
        
        const sendEventSpy = vi.spyOn(session as any, 'sendEvent');
        
        mockSocket.emit('data', part1);
        expect(sendEventSpy).not.toHaveBeenCalled();
        
        mockSocket.emit('data', part2);
        expect(sendEventSpy).toHaveBeenCalledWith(expect.objectContaining({
            output: 'split'
        }));
    });

    it('should handle multiple messages in one chunk', () => {
        const payload1 = { event: 'output', output: 'msg1' };
        const payload2 = { event: 'output', output: 'msg2' };
        const frame1 = createFrame(payload1);
        const frame2 = createFrame(payload2);
        const combined = Buffer.concat([frame1, frame2]);
        
        const sendEventSpy = vi.spyOn(session as any, 'sendEvent');
        
        mockSocket.emit('data', combined);
        
        expect(sendEventSpy).toHaveBeenCalledTimes(2);
        expect(sendEventSpy).toHaveBeenNthCalledWith(1, expect.objectContaining({ output: 'msg1' }));
        expect(sendEventSpy).toHaveBeenNthCalledWith(2, expect.objectContaining({ output: 'msg2' }));
    });

    it('should correlate requests and responses', async () => {
        // Mock sendResponse to verify flow
        const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');
        
        // Trigger initializeRequest
        const initPromise = (session as any).initializeRequest({
            command: 'initialize',
            seq: 1,
            arguments: { adapterID: 'dapper' }
        } as DebugProtocol.InitializeRequest, { adapterID: 'dapper' });

        // Verify request was sent to Python
        expect(mockSocket.write).toHaveBeenCalled();
        const sentData = mockSocket.write.mock.calls[0][0] as Buffer;
        // Skip header (8 bytes)
        const sentJson = JSON.parse(sentData.subarray(8).toString('utf8'));
        expect(sentJson.command).toBe('initialize');
        const requestId = sentJson.id;
        expect(requestId).toBeDefined();

        // Simulate response from Python
        const responsePayload = {
            event: 'response',
            id: requestId,
            success: true,
            body: { supportsConfigurationDoneRequest: true }
        };
        mockSocket.emit('data', createFrame(responsePayload));

        await initPromise;

        expect(sendResponseSpy).toHaveBeenCalled();
        const response = sendResponseSpy.mock.calls[0][0] as DebugProtocol.InitializeResponse;
        expect(response.body?.supportsConfigurationDoneRequest).toBe(true);
    });

    it('should wait for specific events (variablesRequest)', async () => {
        const sendResponseSpy = vi.spyOn(session as any, 'sendResponse');
        
        const varsPromise = (session as any).variablesRequest({
            seq: 0,
            type: 'response',
            request_seq: 2,
            command: 'variables',
            success: true,
            body: {}
        } as DebugProtocol.VariablesResponse, { variablesReference: 123 });

        // Verify request sent
        expect(mockSocket.write).toHaveBeenCalled();
        
        // Simulate 'variables' event from Python
        const eventPayload = {
            event: 'variables',
            variablesReference: 123,
            variables: [{ name: 'x', value: '1' }]
        };
        mockSocket.emit('data', createFrame(eventPayload));

        await varsPromise;

        expect(sendResponseSpy).toHaveBeenCalled();
        const response = sendResponseSpy.mock.calls[0][0] as DebugProtocol.VariablesResponse;
        expect(response.body.variables).toHaveLength(1);
        expect(response.body.variables[0].name).toBe('x');
    });
});
