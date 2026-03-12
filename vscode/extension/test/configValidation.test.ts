import { describe, it, expect } from 'vitest';
import { validateConfig, sanitizeConfig, mergeWithDefaults, defaultConfig } from '../src/webview/utils/configValidation.js';
import type { DebugConfiguration } from '../src/webview/types/debug.js';

function makeValidConfig(overrides: Partial<DebugConfiguration> = {}): DebugConfiguration {
  const base: any = {
    name: 'Test Config',
    type: 'dapper',
    request: 'launch',
    program: 'main.py',
    args: [],
    cwd: '/workspace',
    useIpc: true,
    ipcTransport: 'pipe',
    frameEval: true,
    inProcess: false,
    stopOnEntry: true,
    justMyCode: true,
    ...overrides,
  };
  // include debugServer only when tcp transport or explicitly overridden
  if (base.ipcTransport === 'tcp' || overrides.debugServer !== undefined) {
    base.debugServer = overrides.debugServer ?? 4711;
  }
  return base as DebugConfiguration;
}

describe('validateConfig', () => {
  it('should pass validation with valid config', () => {
    const result = validateConfig(makeValidConfig());
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should fail when name is missing', () => {
    const result = validateConfig(makeValidConfig({ name: undefined as any }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Configuration name is required');
  });

  it('should fail when name is whitespace only', () => {
    const result = validateConfig(makeValidConfig({ name: '   ' }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Configuration name is required');
  });

  it('should fail when both program and module are missing', () => {
    const result = validateConfig(makeValidConfig({ program: undefined as any }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should fail when both program and module are provided', () => {
    const result = validateConfig(makeValidConfig({ program: 'main.py', module: 'pkg.main' }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Launch accepts only one target: program or module');
  });

  it('should fail launch when host/port is also provided', () => {
    const result = validateConfig(makeValidConfig({ program: 'main.py', host: 'localhost', port: 5678 } as any));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Launch accepts only one target: program or module');
  });

  it('should fail when program and module are empty strings', () => {
    const result = validateConfig(makeValidConfig({ program: '' }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should pass when module is provided without program', () => {
    const result = validateConfig(makeValidConfig({ program: undefined as any, module: 'pkg.main' }));
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should fail when subProcess is true but subProcessName is missing', () => {
    const result = validateConfig(makeValidConfig({ subProcess: true }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Subprocess name is required when subprocess debugging is enabled');
  });

  it('should pass when ipcTransport is tcp (useIpc no longer required separately)', () => {
    const result = validateConfig(makeValidConfig({ ipcTransport: 'tcp', useIpc: false }));
    expect(result.valid).toBe(true);
  });

  it('should return multiple errors at once', () => {
    const result = validateConfig({ } as any);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThanOrEqual(2);
    expect(result.errors).toContain('Configuration name is required');
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should pass when subProcess is false even without subProcessName', () => {
    const result = validateConfig(makeValidConfig({ subProcess: false }));
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should validate attach with host and port', () => {
    const result = validateConfig({
      name: 'Attach Remote',
      type: 'dapper',
      request: 'attach',
      host: 'localhost',
      port: 5678,
    } as any);
    expect(result.valid).toBe(true);
  });

  it('should fail attach when no attach target is provided', () => {
    const result = validateConfig({
      name: 'Attach Missing Target',
      type: 'dapper',
      request: 'attach',
    } as any);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Attach requires either processId or host/port');
  });

  it('should fail attach when both processId and host/port are provided', () => {
    const result = validateConfig({
      name: 'Attach Too Many Targets',
      type: 'dapper',
      request: 'attach',
      processId: '${command:pickProcess}',
      host: 'localhost',
      port: 5678,
    } as any);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Attach accepts only one target: processId or host/port');
  });

  it('should fail attach when a launch target is also provided', () => {
    const result = validateConfig({
      name: 'Attach With Program',
      type: 'dapper',
      request: 'attach',
      host: 'localhost',
      port: 5678,
      program: 'main.py',
    } as any);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Attach accepts only one target: processId or host/port');
  });
});

describe('sanitizeConfig', () => {
  it('should remove undefined and null values', () => {
    const config = makeValidConfig({ pythonPath: undefined, env: null as any });
    const result = sanitizeConfig(config);
    expect(result).not.toHaveProperty('pythonPath');
    expect(result).not.toHaveProperty('env');
  });

  it('should keep empty strings', () => {
    const config = makeValidConfig({ name: '' });
    const result = sanitizeConfig(config);
    expect(result.name).toBe('');
  });

  it('should initialize args array when not present', () => {
    const config = makeValidConfig({ args: undefined as any });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.args)).toBe(true);
    expect(result.args).toEqual([]);
  });

  it('should initialize debugOptions array when not present', () => {
    const config = makeValidConfig({ debugOptions: undefined as any });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.debugOptions)).toBe(true);
    expect(result.debugOptions).toEqual([]);
  });

  it('should initialize subProcess arrays when subProcess is true', () => {
    const config = makeValidConfig({ subProcess: true });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.subProcessArgs)).toBe(true);
    expect(Array.isArray(result.subProcessDebugOptions)).toBe(true);
  });

  it('should always set type to dapper', () => {
    const config = makeValidConfig({ type: 'other' as any });
    const result = sanitizeConfig(config);
    expect(result.type).toBe('dapper');
  });

  it('should derive useIpc=true for pipe and unix transport', () => {
    const result1 = sanitizeConfig(makeValidConfig({ ipcTransport: 'pipe', debugServer: 4711 }));
    expect(result1.useIpc).toBe(true);
    expect(result1).not.toHaveProperty('debugServer');

    const result2 = sanitizeConfig(makeValidConfig({ ipcTransport: 'unix', debugServer: 4711 }));
    expect(result2.useIpc).toBe(true);
    expect(result2).not.toHaveProperty('debugServer');
  });

  it('should derive useIpc=false for tcp transport', () => {
    const result = sanitizeConfig(makeValidConfig({ ipcTransport: 'tcp' }));
    expect(result.useIpc).toBe(false);
    expect(result.debugServer).toBe(4711);
  });

  it('should keep both launch targets so validation can reject the config', () => {
    const result = sanitizeConfig(makeValidConfig({ program: '${file}', module: 'mypackage.main' }));
    expect(result.program).toBe('${file}');
    expect(result.module).toBe('mypackage.main');
  });

  it('should keep program when module is empty', () => {
    const result = sanitizeConfig(makeValidConfig({ program: 'app.py', module: '' }));
    expect(result.program).toBe('app.py');
  });

  it('should not mutate the original object', () => {
    const config = makeValidConfig({ type: 'other' as any });
    const originalName = config.name;
    sanitizeConfig(config);
    expect(config.type).toBe('other');
    expect(config.name).toBe(originalName);
  });

  it('should deep copy the config', () => {
    const config = makeValidConfig({ args: ['--verbose'] });
    const result = sanitizeConfig(config);
    result.args.push('--extra');
    expect(config.args).toEqual(['--verbose']);
  });
});

describe('mergeWithDefaults', () => {
  it('should fill all defaults when given empty config', () => {
    const result = mergeWithDefaults({});
    expect(result.type).toBe(defaultConfig.type);
    expect(result.request).toBe(defaultConfig.request);
    expect(result.program).toBe(defaultConfig.program);
    expect(result.cwd).toBe(defaultConfig.cwd);
    // debugServer is intentionally dropped when transport isn't tcp
    if (result.ipcTransport === 'tcp') {
      expect(result.debugServer).toBe(defaultConfig.debugServer);
    } else {
      expect(result).not.toHaveProperty('debugServer');
    }
    expect(result.useIpc).toBe(defaultConfig.useIpc);
    expect(result.ipcTransport).toBe(defaultConfig.ipcTransport);
    expect(result.frameEval).toBe(defaultConfig.frameEval);
    expect(result.inProcess).toBe(defaultConfig.inProcess);
    expect(result.stopOnEntry).toBe(defaultConfig.stopOnEntry);
    expect(result.justMyCode).toBe(defaultConfig.justMyCode);
  });

  it('should include debugServer when tcp transport is requested', () => {
    const result = mergeWithDefaults({ ipcTransport: 'tcp' });
    expect(result.debugServer).toBe(4711);
  });

  it('should use provided name over default', () => {
    const result = mergeWithDefaults({ name: 'My Config' });
    expect(result.name).toBe('My Config');
  });

  it('should default name to "Dapper Debug" when not provided', () => {
    const result = mergeWithDefaults({});
    expect(result.name).toBe('Dapper Debug');
  });

  it('should trim whitespace from name', () => {
    const result = mergeWithDefaults({ name: '  My Config  ' });
    expect(result.name).toBe('My Config');
  });

  it('should merge env objects', () => {
    const result = mergeWithDefaults({ env: { MY_VAR: 'value' } });
    expect(result.env).toEqual({ MY_VAR: 'value' });
  });

  it('should merge debugOptions arrays', () => {
    const result = mergeWithDefaults({ debugOptions: ['RedirectOutput'] });
    expect(result.debugOptions).toContain('RedirectOutput');
  });

  it('should handle subprocess defaults when subProcess is true', () => {
    const result = mergeWithDefaults({ subProcess: true, subProcessArgs: ['--child'] });
    expect(result.subProcessArgs).toContain('--child');
    expect(result.subProcessEnv).toBeDefined();
    expect(result.subProcessDebugOptions).toBeDefined();
  });

  it('should not add subprocess fields when subProcess is false', () => {
    const result = mergeWithDefaults({ subProcess: false });
    expect(result.subProcessEnv).toBeUndefined();
    expect(result.subProcessArgs).toBeUndefined();
    expect(result.subProcessDebugOptions).toBeUndefined();
  });
});
