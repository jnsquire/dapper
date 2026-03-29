import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGetPythonEnvironment } = vi.hoisted(() => ({
  mockGetPythonEnvironment: vi.fn(),
}));

vi.mock('vscode', () => {
  const firstWorkspace = {
    uri: {
      fsPath: '/workspace',
      toString: () => 'file:///workspace',
    },
  };

  return {
    workspace: {
      workspaceFolders: [firstWorkspace],
      getWorkspaceFolder: vi.fn(() => firstWorkspace),
    },
    window: {
      activeTextEditor: undefined,
    },
  };
});

vi.mock('../src/python/environment.js', async () => {
  class PythonEnvironmentError extends Error {
    code: string;

    constructor(code: string, message: string) {
      super(message);
      this.code = code;
      this.name = 'PythonEnvironmentError';
    }
  }

  return {
    PythonEnvironmentManager: {
      getPythonEnvironment: mockGetPythonEnvironment,
    },
    PythonEnvironmentError,
  };
});

import { createExtensionApi } from '../src/api.js';
import { PythonEnvironmentError } from '../src/python/environment.js';

describe('Dapper extension API', () => {
  beforeEach(() => {
    mockGetPythonEnvironment.mockReset();
  });

  it('reports python_extension_missing through the public runtime API', async () => {
    mockGetPythonEnvironment.mockRejectedValue(
      new PythonEnvironmentError('python_extension_missing', 'Python extension is not installed'),
    );

    const api = createExtensionApi();
    const result = await api.getWorkspacePythonRuntime();

    expect(result.ok).toBe(false);
    if (result.ok) {
      return;
    }

    expect(result.code).toBe('python_extension_missing');
    expect(result.message).toContain('Python extension is not installed');
    expect(result.selection.kind).toBe('first-workspace');
  });

  it('reports python_extension_api_unavailable through the public runtime API', async () => {
    mockGetPythonEnvironment.mockRejectedValue(
      new PythonEnvironmentError(
        'python_extension_api_unavailable',
        'Python extension does not expose a compatible environments.resolveEnvironment API',
      ),
    );

    const api = createExtensionApi();
    const result = await api.getWorkspacePythonRuntime();

    expect(result.ok).toBe(false);
    if (result.ok) {
      return;
    }

    expect(result.code).toBe('python_extension_api_unavailable');
    expect(result.message).toContain('compatible environments.resolveEnvironment API');
    expect(result.selection.kind).toBe('first-workspace');
  });
});