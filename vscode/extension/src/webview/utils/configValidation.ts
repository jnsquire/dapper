import { DebugConfiguration } from '../types/debug.js';

export const defaultConfig: Omit<DebugConfiguration, 'name'> = {
  type: 'dapper',
  request: 'launch',
  program: '${file}',
  args: [],
  cwd: '${workspaceFolder}',
  // debugServer default is defined here for completeness but is stripped
  // by mergeWithDefaults/sanitizeConfig unless the transport is TCP.
  debugServer: 4711,
  useIpc: true,
  ipcTransport: 'pipe',
  frameEval: true,
  inProcess: false,
  stopOnEntry: true,
  justMyCode: true,
  pythonPath: '${config:python.defaultInterpreterPath}',
  console: 'integratedTerminal',
  redirectOutput: true,
  showReturnValue: true,
  logToFile: false,
  django: false,
  flask: false,
  jinja: false,
  gevent: false,
  debugOptions: [],
  subProcess: false
};

export function validateConfig(config: Partial<DebugConfiguration>): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  const hasProgram = Boolean(config.program?.trim());
  const hasModule = Boolean(config.module?.trim());
  const rawProcessId = config.processId;
  const hasProcessId = typeof rawProcessId === 'number'
    || (typeof rawProcessId === 'string' && rawProcessId.trim().length > 0);
  const host = typeof config.host === 'string' ? config.host.trim() : '';
  const rawPort = config.port as unknown;
  const hasPort = typeof rawPort === 'number' && Number.isFinite(rawPort)
    || (typeof rawPort === 'string' && rawPort.trim().length > 0);
  const hasHostPort = Boolean(host) && hasPort;
  const explicitTargetCount = [hasProgram, hasModule, hasProcessId, hasHostPort].filter(Boolean).length;

  if (!config.name?.trim()) {
    errors.push('Configuration name is required');
  }

  if (config.request === 'attach') {
    if (!hasProcessId && !hasHostPort) {
      errors.push('Attach requires either processId or host/port');
    }
    if (explicitTargetCount > 1) {
      errors.push('Attach accepts only one target: processId or host/port');
    }
  } else {
    if (!hasProgram && !hasModule) {
      errors.push('Program path or module name is required');
    }
    if (explicitTargetCount > 1) {
      errors.push('Launch accepts only one target: program or module');
    }
  }

  if (config.subProcess && !config.subProcessName?.trim()) {
    errors.push('Subprocess name is required when subprocess debugging is enabled');
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

export function sanitizeConfig(config: DebugConfiguration): DebugConfiguration {
  // Create a deep copy to avoid mutating the original
  const sanitized = JSON.parse(JSON.stringify(config));
  
  // Remove undefined and null values (keep empty strings for validation)
  Object.keys(sanitized).forEach(key => {
    if (sanitized[key] === undefined || sanitized[key] === null) {
      delete sanitized[key];
    }
  });

  // Derive useIpc from transport: pipe and unix are IPC, tcp is not
  sanitized.useIpc = sanitized.ipcTransport !== 'tcp';

  // When the transport isn't TCP we don't want a debugServer field at all;
  // VS Code interprets its presence as an instruction to connect to an
  // already-running adapter instead of launching one.  See the bug where the
  // wizard was returning a default config containing debugServer even though
  // the transport was pipe.
  if (sanitized.ipcTransport !== 'tcp') {
    delete sanitized.debugServer;
  }

  if (!sanitized.program?.trim()) {
    delete sanitized.program;
  }
  if (!sanitized.module?.trim()) {
    delete sanitized.module;
  }
  if (typeof sanitized.host !== 'string' || !sanitized.host.trim()) {
    delete sanitized.host;
  }
  if (sanitized.port === '' || sanitized.port === null || sanitized.port === undefined) {
    delete sanitized.port;
  }
  if (sanitized.processId === '' || sanitized.processId === null || sanitized.processId === undefined) {
    delete sanitized.processId;
  }

  // Ensure arrays are properly initialized
  if (!Array.isArray(sanitized.args)) sanitized.args = [];
  if (!Array.isArray(sanitized.debugOptions)) sanitized.debugOptions = [];
  
  // Ensure subprocess arrays are properly initialized
  if (sanitized.subProcess) {
    if (!Array.isArray(sanitized.subProcessArgs)) sanitized.subProcessArgs = [];
    if (!Array.isArray(sanitized.subProcessDebugOptions)) sanitized.subProcessDebugOptions = [];
  }

  // Ensure type is always 'dapper'
  sanitized.type = 'dapper';

  return sanitized;
}

export function mergeWithDefaults(config: Partial<DebugConfiguration>): DebugConfiguration {
  // Ensure name is always a string with a default value
  const name = config.name?.trim() || 'Dapper Debug';
  
  const merged: DebugConfiguration = {
    ...defaultConfig,
    ...config,
    name, // Ensured to be a string
    // Ensure nested objects are properly merged
    env: { ...(defaultConfig.env || {}), ...(config.env || {}) },
    debugOptions: [...(defaultConfig.debugOptions || []), ...(config.debugOptions || [])].filter(Boolean),
  };

  // strip debugServer unless tcp transport is chosen; defaults above always
  // include a value so this handles the initial-configuration case as well.
  if (merged.ipcTransport !== 'tcp') {
    // ``debugServer`` is not a required field on the wider configuration type, but
    // TS still complains when using ``delete`` against a typed object.  use an
    // escape hatch so we can remove it cleanly when the transport isn't TCP.
    delete (merged as any).debugServer;
  }
  
  // Handle subprocess defaults if needed
  if (config.subProcess) {
    merged.subProcessEnv = { 
      ...(defaultConfig.subProcessEnv || {}), 
      ...(config.subProcessEnv || {}) 
    };
    merged.subProcessArgs = [
      ...(defaultConfig.subProcessArgs || []), 
      ...(config.subProcessArgs || [])
    ].filter(Boolean);
    merged.subProcessDebugOptions = [
      ...(defaultConfig.subProcessDebugOptions || []), 
      ...(config.subProcessDebugOptions || [])
    ].filter(Boolean);
  }
  
  return merged;
}
