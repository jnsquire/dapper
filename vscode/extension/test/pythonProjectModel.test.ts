import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { afterEach, describe, expect, it } from 'vitest';

import { PythonProjectModelService } from '../src/python/projectModel.js';

describe('PythonProjectModelService', () => {
  const tempRoots: string[] = [];

  afterEach(() => {
    for (const tempRoot of tempRoots.splice(0)) {
      fs.rmSync(tempRoot, { recursive: true, force: true });
    }
  });

  it('reports source roots, test roots, config files, and package boundaries', async () => {
    const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-project-model-'));
    tempRoots.push(tempRoot);

    fs.mkdirSync(path.join(tempRoot, 'src', 'samplepkg'), { recursive: true });
    fs.mkdirSync(path.join(tempRoot, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(tempRoot, 'pyproject.toml'), '[project]\nname = "sample"\n[tool.ruff]\nline-length = 99\n');
    fs.writeFileSync(path.join(tempRoot, 'setup.cfg'), '[tool:pytest]\naddopts = -q\n');
    fs.writeFileSync(path.join(tempRoot, 'src', 'samplepkg', '__init__.py'), '');
    fs.writeFileSync(path.join(tempRoot, 'src', 'samplepkg', 'module.py'), 'value = 1\n');
    fs.writeFileSync(path.join(tempRoot, 'tests', 'conftest.py'), '');

    const service = new PythonProjectModelService({
      getSnapshot: async () => ({
        workspaceFolder: tempRoot,
        searchRoots: [tempRoot],
        python: {
          available: true,
          source: 'activeInterpreter',
          pythonPath: '/workspace/.venv/bin/python',
          version: '3.12',
          venvPath: '/workspace/.venv',
        },
      }),
    } as any);

    const result = await service.getProjectModel({ searchRootPath: tempRoot });

    expect(result.searchRoots).toEqual([tempRoot]);
    expect(result.python.pythonPath).toBe('/workspace/.venv/bin/python');
    expect(result.sourceRoots).toEqual([
      expect.objectContaining({ path: path.join(tempRoot, 'src') }),
    ]);
    expect(result.testRoots).toEqual([
      expect.objectContaining({ path: path.join(tempRoot, 'tests') }),
    ]);
    expect(result.configFiles).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'pyproject.toml', path: path.join(tempRoot, 'pyproject.toml') }),
      expect.objectContaining({ kind: 'setup.cfg', path: path.join(tempRoot, 'setup.cfg') }),
    ]));
    expect(result.packageBoundaries).toEqual([
      expect.objectContaining({
        name: 'samplepkg',
        path: path.join(tempRoot, 'src', 'samplepkg'),
        sourceRoot: path.join(tempRoot, 'src'),
        kind: 'regular-package',
      }),
    ]);
  });
});