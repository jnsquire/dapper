import { EventEmitter } from 'events';

import { afterEach, describe, expect, it, vi } from 'vitest';

const { spawnMock } = vi.hoisted(() => ({
  spawnMock: vi.fn(),
}));

vi.mock('child_process', () => ({
  spawn: spawnMock,
}));

import { runLoggedProcessResult } from '../src/environment/processRunner.js';

const fakeOutputChannel: any = {
  info: () => {}, debug: () => {}, warn: () => {}, error: () => {}, trace: () => {},
};

class MockChildProcess extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
}

describe('runLoggedProcessResult', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('preserves raw stdout chunk boundaries without inserting newlines', async () => {
    const child = new MockChildProcess();
    spawnMock.mockReturnValue(child as any);

    const resultPromise = runLoggedProcessResult(
      fakeOutputChannel,
      'python',
      ['-m', 'ty', 'check'],
      { label: 'ty check' },
    );

    child.stdout.emit('data', Buffer.from('[{"description":"Module `sys` has no member `monit'));
    child.stdout.emit('data', Buffer.from('oring`"}]'));
    child.emit('close', 1);

    const result = await resultPromise;

    expect(result.ok).toBe(false);
    expect(result.code).toBe(1);
    expect(result.stdout).toBe('[{"description":"Module `sys` has no member `monitoring`"}]');
  });

  it('keeps stdout and stderr separate while combining them for output', async () => {
    const child = new MockChildProcess();
    spawnMock.mockReturnValue(child as any);

    const resultPromise = runLoggedProcessResult(
      fakeOutputChannel,
      'python',
      ['-m', 'tool'],
      { label: 'tool run' },
    );

    child.stdout.emit('data', Buffer.from('hello'));
    child.stderr.emit('data', Buffer.from('warning'));
    child.emit('close', 0);

    const result = await resultPromise;

    expect(result.ok).toBe(true);
    expect(result.stdout).toBe('hello');
    expect(result.stderr).toBe('warning');
    expect(result.output).toBe('hello\nwarning');
  });
});