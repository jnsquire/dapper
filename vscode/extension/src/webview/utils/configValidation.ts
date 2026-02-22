import { DebugConfiguration } from '../types/debug.js';

export const defaultConfig: Omit<DebugConfiguration, 'name'> = {
  type: 'dapper',
  request: 'launch',
  program: '${file}',
  args: [],
  cwd: '${workspaceFolder}',
  debugServer: 4711,
  useIpc: true,
  ipcTransport: 'pipe',
  frameEval: true,
  inProcess: false,
  stopOnEntry: true,
  justMyCode: true,
  pythonPath: '${config:python.pythonPath}',
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

  if (!config.name?.trim()) {
    errors.push('Configuration name is required');
  }

  if (!config.program?.trim()) {
    errors.push('Program path is required');
  }

  if (config.subProcess && !config.subProcessName?.trim()) {
    errors.push('Subprocess name is required when subprocess debugging is enabled');
  }

  if (config.useIpc && !config.ipcTransport) {
    errors.push('IPC transport method is required when using IPC');
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
