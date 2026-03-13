/*
Extension Host Launch Harness

This mock harness exercises the `dapper_launch` tool interface through the
extension's Vitest suite.  It lives under `vscode/extension/test`, and the
accompanying Markdown page in `doc/development/extension-launch-harness.md`
contains the same information in a more permanent, searchable location.

Key points:
  * Completely fake: no real adapter, Python process, or VS Code window is
    ever spawned.  All interactions happen via the mocked `vscode` layer.
  * Designed for agent-driven coverage of launch scenarios.
  * Primary entry points for tests are `createLaunchHarness` and
    `LaunchTool.invoke(...)`.

What the harness covers:
  - active Python editor launch
  - workspace-relative file launch
  - module launch
  - named Dapper config from `launch.json`
  - named saved Dapper config from `dapper.debug`
  - explicit `pythonPath` or `venvPath`
  - wait-for-stop flow via fake debug events

Recommended pattern for new cases:

  const harness = createLaunchHarness({ workspaceRoot: tmpRoot });
  const registry = new JournalRegistry();
  const launchService = new LaunchService(registry);
  const launchTool = new LaunchTool(registry, launchService);

  harness.setActivePythonFile(path.join(tmpRoot, 'app.py'));
  const result = await invokeLaunchTool(launchTool, { target: { currentFile: true } });
  expect(result.configuration.program).toContain('app.py');

Harness controls (methods exported by `LaunchHarness`):
  - setActivePythonFile(filePath)
  - setSavedDapperConfig(config)
  - setLaunchConfigurations(configs)
  - setPythonInterpreter(pythonPath)
  - fireStopped(body)
  - fireTerminated(body)
  - createCancellationToken()

Quick debugging tips:
  * If a test hangs, check whether `waitForStop: true` needs `fireStopped(...)` to receive
  * Named config failures usually stem from launch or dapper configuration stubs
  * Interpreter issues can be traced via `setPythonInterpreter(...)`
  * If a test hangs, check whether `waitForStop: true` needs `fireStopped(...)
  * Named config failures usually stem from launch or dapper configuration stubs
  * Interpreter issues can be traced via `setPythonInterpreter(...)`

Related agent-layer acceptance assets (for higher‑level, end‑to‑end workflows):
  - `vscode/extension/test/AGENT_LAYER_DEBUG_SCRIPT.md`
  - `vscode/extension/test/fixtures/agent_debug_workspace/README.md`
*/

import { vi } from 'vitest';
import { fireDebugEvent } from '../__mocks__/vscode.mjs';

const vscode = await import('vscode');

export interface LaunchHarnessOptions {
  workspaceRoot?: string;
  activeInterpreter?: string;
}

export interface LaunchHarness {
  workspaceRoot: string;
  lastStartDebuggingCall: { folder: unknown; config: Record<string, unknown> } | undefined;
  session: any;
  sessionForRegistry(): any;
  onSessionStarted(callback: (session: any) => void): void;
  setActivePythonFile(filePath: string): void;
  setSavedDapperConfig(config: Record<string, unknown> | undefined): void;
  setLaunchConfigurations(configs: Array<Record<string, unknown>>): void;
  setPythonInterpreter(pythonPath: string): void;
  fireStopped(body?: Record<string, unknown>): void;
  fireTerminated(body?: Record<string, unknown>): void;
  createCancellationToken(): { isCancellationRequested: boolean };
}

export function createLaunchHarness(options: LaunchHarnessOptions = {}): LaunchHarness {
  const workspaceRoot = options.workspaceRoot ?? '/workspace/project';
  let savedDapperConfig: Record<string, unknown> | undefined;
  let launchConfigurations: Array<Record<string, unknown>> = [];
  let activeInterpreter = options.activeInterpreter ?? `${workspaceRoot}/.venv/bin/python`;
  let sessionCounter = 0;
  const sessionStartedCallbacks: Array<(session: any) => void> = [];

  const folder = {
    index: 0,
    name: 'project',
    uri: { fsPath: workspaceRoot, scheme: 'file' },
  };

  Object.defineProperty(vscode.workspace, 'workspaceFolders', {
    configurable: true,
    value: [folder],
  });
  (vscode.workspace as any).getWorkspaceFolder = vi.fn((uri: { fsPath?: string }) => {
    if (typeof uri?.fsPath === 'string' && uri.fsPath.startsWith(workspaceRoot)) {
      return folder;
    }
    return undefined;
  });
  (vscode.workspace as any).asRelativePath = vi.fn((uriOrPath: { fsPath?: string } | string) => {
    const rawPath = typeof uriOrPath === 'string' ? uriOrPath : uriOrPath?.fsPath ?? '';
    return rawPath.startsWith(workspaceRoot)
      ? rawPath.slice(workspaceRoot.length).replace(/^[\\/]+/, '')
      : rawPath;
  });
  (vscode.workspace as any).getConfiguration = vi.fn((section?: string) => {
    const makeConfig = (getValue: (key: string, defaultValue?: unknown) => unknown) => ({
      get: getValue,
      has: vi.fn(() => false),
      inspect: vi.fn(() => undefined),
      update: vi.fn(),
    });

    if (section === 'dapper') {
      return makeConfig((key: string) => key === 'debug' ? savedDapperConfig : undefined);
    }
    if (section === 'launch') {
      return makeConfig((key: string, defaultValue?: unknown) => key === 'configurations' ? launchConfigurations : defaultValue);
    }
    return makeConfig((_key: string, defaultValue?: unknown) => defaultValue);
  });

  (vscode.extensions as any).getExtension = vi.fn((id: string) => {
    if (id !== 'ms-python.python') {
      return undefined;
    }
    return {
      id,
      isActive: true,
      extensionUri: { fsPath: '/extensions/ms-python.python', scheme: 'file' },
      extensionPath: '/extensions/ms-python.python',
      packageJSON: {},
      extensionKind: 1,
      activate: vi.fn(async () => undefined),
      exports: {
        environments: {
          resolveEnvironment: vi.fn(async () => ({
            path: activeInterpreter,
            version: { major: 3, minor: 11 },
            envVars: Promise.resolve({ PYTHONPATH: '' }),
          })),
        },
      },
    };
  });

  let lastStartDebuggingCall: { folder: unknown; config: Record<string, unknown> } | undefined;
  let session: any;
  (vscode.debug as any).startDebugging = vi.fn(async (debugFolder: unknown, config: Record<string, unknown>) => {
    lastStartDebuggingCall = { folder: debugFolder, config };
    sessionCounter += 1;
    session = {
      id: `session-${sessionCounter}`,
      type: 'dapper',
      name: String(config.name ?? `session-${sessionCounter}`),
      configuration: config,
      workspaceFolder: debugFolder,
      customRequest: vi.fn(async () => undefined),
    };
    vscode.debug.activeDebugSession = session;
    for (const callback of sessionStartedCallbacks) {
      callback(session);
    }
    const { fireDebugEvent } = await import('../__mocks__/vscode.mjs');
    fireDebugEvent('onDidStartDebugSession', session);
    return true;
  }) as any;

  const setActivePythonFile = (filePath: string): void => {
    vscode.window.activeTextEditor = {
      document: {
        languageId: 'python',
        isUntitled: false,
        uri: { fsPath: filePath, scheme: 'file' },
      },
    } as any;
  };

  return {
    workspaceRoot,
    get lastStartDebuggingCall() {
      return lastStartDebuggingCall;
    },
    get session() {
      return session;
    },
    sessionForRegistry() {
      return session;
    },
    onSessionStarted(callback) {
      sessionStartedCallbacks.push(callback);
    },
    setActivePythonFile,
    setSavedDapperConfig(config) {
      savedDapperConfig = config;
    },
    setLaunchConfigurations(configs) {
      launchConfigurations = configs;
    },
    setPythonInterpreter(pythonPath: string) {
      activeInterpreter = pythonPath;
    },
    fireStopped(body = {}) {
      fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
        session,
        event: 'stopped',
        body,
      });
    },
    fireTerminated(body = {}) {
      fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
        session,
        event: 'terminated',
        body,
      });
    },
    createCancellationToken() {
      return { isCancellationRequested: false };
    },
  };
}