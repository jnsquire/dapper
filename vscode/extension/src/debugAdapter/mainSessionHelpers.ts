import * as vscode from 'vscode';
import { delimiter as pathDelimiter } from 'path';
import type { EnvironmentManager } from '../environment/EnvironmentManager.js';
import { buildDefaultLogFilePath } from './logFileNaming.js';
import {
  type AttachRequestArguments,
  type LaunchRequestArguments,
} from './debugAdapterTypes.js';

export type PreparedEnvironment = Awaited<ReturnType<EnvironmentManager['prepareEnvironment']>>;

export interface ResolvedAttachTarget {
  processId?: number;
  host: string;
  port?: number;
  program: string;
  moduleName: string;
}

export function resolveProcessId(config: vscode.DebugConfiguration): number | undefined {
  const raw = (config as AttachRequestArguments).processId;
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) {
    return raw;
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (!trimmed) {
      return undefined;
    }
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return undefined;
}

export function resolveAttachTarget(config: vscode.DebugConfiguration): ResolvedAttachTarget {
  const target: ResolvedAttachTarget = {
    processId: resolveProcessId(config),
    host: typeof config.host === 'string' ? config.host.trim() : '',
    port: resolveAttachPort(config.port),
    program: typeof config.program === 'string' ? config.program.trim() : '',
    moduleName: typeof config.module === 'string' ? config.module.trim() : '',
  };

  assertSingleLaunchTarget(target.program, target.moduleName, 'Provide exactly one target: processId, host/port, program, or module.');

  const hasHostPort = Boolean(target.host) && target.port != null;
  if (hasHostPort && (target.program || target.moduleName)) {
    throw new Error('Provide exactly one target: processId, host/port, program, or module.');
  }
  if (target.processId != null && (target.program || target.moduleName)) {
    throw new Error('Provide exactly one target: processId, host/port, program, or module.');
  }

  return target;
}

export function assertSingleLaunchTarget(program: string, moduleName: string, message: string): void {
  if (program && moduleName) {
    throw new Error(message);
  }
}

export function resolveLaunchToken(config: vscode.DebugConfiguration): string | undefined {
  const candidate = config as Record<string, unknown>;
  return typeof candidate.__dapperLaunchToken === 'string' ? candidate.__dapperLaunchToken : undefined;
}

export function buildProcessEnv(
  extensionVersion: string,
  envInfo: PreparedEnvironment,
  config: LaunchRequestArguments | AttachRequestArguments,
  session: vscode.DebugSession,
): { terminalEnv: Record<string, string>; logFile: string } {
  const debuggerConfig = vscode.workspace.getConfiguration('dapper.debugger');
  const configuredLogFile = (debuggerConfig.get<string>('logFile', '') || '').trim();
  let logFile: string;
  if (configuredLogFile) {
    const wsFolder = session.workspaceFolder?.uri.fsPath
      ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      ?? '';
    logFile = configuredLogFile.replace(/\$\{workspaceFolder\}/g, wsFolder);
    logFile = logFile.replace(/%([^%]+)%/g, (_match: string, name: string) => process.env[name] ?? `%${name}%`);
    if (process.platform !== 'win32') {
      logFile = logFile.replace(/\\/g, '/');
    }
  } else {
    logFile = buildDefaultLogFilePath('debug', session.id);
  }

  const debugLogLevel = (debuggerConfig.get<string>('logLevel', 'DEBUG') || 'DEBUG').toUpperCase();
  const rawEnv = {
    ...process.env,
    ...(config.env || {}),
    DAPPER_MANAGED_VENV: envInfo.venvPath || '',
    DAPPER_VERSION_EXPECTED: extensionVersion,
    DAPPER_LOG_FILE: logFile,
    DAPPER_LOG_LEVEL: debugLogLevel,
  };
  const terminalEnv: Record<string, string> = {};
  for (const [key, value] of Object.entries(rawEnv)) {
    if (typeof value === 'string') {
      terminalEnv[key] = value;
    }
  }

  if (envInfo.dapperLibPath) {
    const existing = terminalEnv.PYTHONPATH || '';
    terminalEnv.PYTHONPATH = existing
      ? `${envInfo.dapperLibPath}${pathDelimiter}${existing}`
      : envInfo.dapperLibPath;
  }

  return { terminalEnv, logFile };
}

export function buildLauncherArgs(
  config: vscode.DebugConfiguration,
  pythonIpcPort: number,
  childIpcPort: number | undefined,
  onMissingTarget: () => void,
): string[] {
  const args: string[] = ['-m', 'dapper.launcher'];
  const program = config.program as string | undefined;
  const moduleName = config.module as string | undefined;

  if (program) {
    args.push('--program', String(program).replace(/\\/g, '/'));
  } else if (moduleName) {
    args.push('--module', String(moduleName));
  } else {
    onMissingTarget();
  }

  if (Array.isArray(config.moduleSearchPaths)) {
    for (const moduleSearchPath of config.moduleSearchPaths) {
      args.push('--module-search-path', String(moduleSearchPath));
    }
  }
  if (Array.isArray(config.args)) {
    for (const arg of config.args) {
      args.push('--arg', String(arg));
    }
  }
  if (config.stopOnEntry) {
    args.push('--stop-on-entry');
  }
  if (config.noDebug) {
    args.push('--no-debug');
  }
  if (config.subprocessAutoAttach) {
    args.push('--subprocess-auto-attach');
    if (childIpcPort != null) {
      args.push('--subprocess-ipc-port', childIpcPort.toString());
    }
  }

  args.push('--ipc', 'tcp', '--ipc-port', pythonIpcPort.toString());
  return args;
}

function resolveAttachPort(rawPort: unknown): number | undefined {
  const port = typeof rawPort === 'number'
    ? rawPort
    : typeof rawPort === 'string' && rawPort.trim()
      ? Number(rawPort)
      : undefined;
  return typeof port === 'number' && Number.isInteger(port) && port > 0 ? port : undefined;
}