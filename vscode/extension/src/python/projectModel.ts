import * as fs from 'fs';
import * as path from 'path';

import { collectEnvironmentSearchRoots } from '../environment/paths.js';
import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';

export interface PythonProjectModelOptions extends EnvironmentSnapshotOptions {}

export interface PythonProjectRoot {
  path: string;
  reason: string;
}

export interface PythonProjectConfigFile {
  kind:
    | 'pyproject.toml'
    | 'setup.cfg'
    | 'setup.py'
    | 'pytest.ini'
    | 'tox.ini'
    | 'ruff.toml'
    | '.ruff.toml'
    | 'ty.toml'
    | '.ty.toml';
  path: string;
  sections?: string[];
}

export interface PythonPackageBoundary {
  name: string;
  path: string;
  sourceRoot: string;
  kind: 'regular-package';
}

export interface PythonProjectModelResult {
  generatedAt: string;
  workspaceFolder?: string;
  searchRootPath?: string;
  searchRoots: string[];
  python: {
    available: boolean;
    source?: 'activeInterpreter' | 'workspaceVenv' | 'none';
    pythonPath?: string;
    version?: string;
    venvPath?: string;
  };
  sourceRoots: PythonProjectRoot[];
  testRoots: PythonProjectRoot[];
  configFiles: PythonProjectConfigFile[];
  packageBoundaries: PythonPackageBoundary[];
}

const CONFIG_FILES = [
  'pyproject.toml',
  'setup.cfg',
  'setup.py',
  'pytest.ini',
  'tox.ini',
  'ruff.toml',
  '.ruff.toml',
  'ty.toml',
  '.ty.toml',
] as const;

const SKIP_DIR_NAMES = new Set([
  '.git',
  '.hg',
  '.svn',
  '.mypy_cache',
  '.nox',
  '.pytest_cache',
  '.ruff_cache',
  '.tox',
  '.venv',
  '.vscode',
  '__pycache__',
  'build',
  'dist',
  'node_modules',
  'site',
  'temp',
  'venv',
]);

const MAX_SCAN_DEPTH = 4;

export class PythonProjectModelService {
  constructor(private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>) {}

  async getProjectModel(options: PythonProjectModelOptions = {}): Promise<PythonProjectModelResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const searchRoots = snapshot.searchRoots.length > 0
      ? snapshot.searchRoots
      : collectEnvironmentSearchRoots(options.searchRootPath, options.workspaceFolder);
    const packageBoundaries = this._detectPackageBoundaries(searchRoots);
    const sourceRoots = this._detectSourceRoots(searchRoots, packageBoundaries);
    const testRoots = this._detectTestRoots(searchRoots);
    const configFiles = this._detectConfigFiles(searchRoots);

    return {
      generatedAt: new Date().toISOString(),
      workspaceFolder: snapshot.workspaceFolder,
      searchRootPath: options.searchRootPath,
      searchRoots,
      python: {
        available: snapshot.python.available,
        source: snapshot.python.source,
        pythonPath: snapshot.python.pythonPath,
        version: snapshot.python.version,
        venvPath: snapshot.python.venvPath,
      },
      sourceRoots,
      testRoots,
      configFiles,
      packageBoundaries,
    };
  }

  private _detectConfigFiles(searchRoots: string[]): PythonProjectConfigFile[] {
    const files: PythonProjectConfigFile[] = [];
    const seen = new Set<string>();

    for (const root of searchRoots) {
      for (const configName of CONFIG_FILES) {
        const configPath = path.join(root, configName);
        if (!fs.existsSync(configPath) || seen.has(configPath)) {
          continue;
        }
        seen.add(configPath);
        files.push({
          kind: configName,
          path: configPath,
          sections: configName === 'pyproject.toml' || configName === 'setup.cfg'
            ? this._detectConfigSections(configPath)
            : undefined,
        });
      }
    }

    return files;
  }

  private _detectPackageBoundaries(searchRoots: string[]): PythonPackageBoundary[] {
    const packageDirs = this._findPackageDirectories(searchRoots);
    return packageDirs.map(({ packagePath, sourceRoot }) => ({
      name: this._buildPackageName(sourceRoot, packagePath),
      path: packagePath,
      sourceRoot,
      kind: 'regular-package',
    }));
  }

  private _detectSourceRoots(
    searchRoots: string[],
    packageBoundaries: PythonPackageBoundary[],
  ): PythonProjectRoot[] {
    const roots = new Map<string, PythonProjectRoot>();

    for (const boundary of packageBoundaries) {
      roots.set(boundary.sourceRoot, {
        path: boundary.sourceRoot,
        reason: 'package-parent',
      });
    }

    for (const root of searchRoots) {
      const srcPath = path.join(root, 'src');
      if (fs.existsSync(srcPath) && fs.statSync(srcPath).isDirectory()) {
        roots.set(srcPath, {
          path: srcPath,
          reason: 'src-directory',
        });
      }
    }

    return [...roots.values()];
  }

  private _detectTestRoots(searchRoots: string[]): PythonProjectRoot[] {
    const roots = new Map<string, PythonProjectRoot>();

    for (const root of searchRoots) {
      this._walkDirectories(root, 0, directoryPath => {
        const basename = path.basename(directoryPath);
        if (basename === 'tests' || basename === 'test') {
          roots.set(directoryPath, { path: directoryPath, reason: 'directory-name' });
        }

        if (fs.existsSync(path.join(directoryPath, 'conftest.py'))) {
          roots.set(directoryPath, { path: directoryPath, reason: 'conftest.py' });
        }
      });
    }

    return [...roots.values()];
  }

  private _findPackageDirectories(searchRoots: string[]): Array<{ packagePath: string; sourceRoot: string }> {
    const packages = new Map<string, { packagePath: string; sourceRoot: string }>();

    for (const root of searchRoots) {
      this._walkDirectories(root, 0, directoryPath => {
        if (!fs.existsSync(path.join(directoryPath, '__init__.py'))) {
          return;
        }

        const sourceRoot = this._determineSourceRoot(root, directoryPath);
        const key = `${sourceRoot}::${directoryPath}`;
        if (!packages.has(key)) {
          packages.set(key, { packagePath: directoryPath, sourceRoot });
        }
      });
    }

    return [...packages.values()];
  }

  private _determineSourceRoot(searchRoot: string, packagePath: string): string {
    const srcCandidate = path.join(searchRoot, 'src');
    if (this._isPathInside(srcCandidate, packagePath)) {
      return srcCandidate;
    }
    return path.dirname(packagePath);
  }

  private _buildPackageName(sourceRoot: string, packagePath: string): string {
    const relativePath = path.relative(sourceRoot, packagePath);
    const segments = relativePath.split(path.sep).filter(Boolean);
    return segments.join('.') || path.basename(packagePath);
  }

  private _detectConfigSections(configPath: string): string[] {
    try {
      const content = fs.readFileSync(configPath, 'utf8');
      const matches = [...content.matchAll(/^\s*\[([^\]]+)\]\s*$/gm)];
      return matches.map(match => match[1]).filter(Boolean);
    } catch {
      return [];
    }
  }

  private _walkDirectories(root: string, depth: number, visit: (directoryPath: string) => void): void {
    if (!fs.existsSync(root)) {
      return;
    }

    let stats: fs.Stats;
    try {
      stats = fs.statSync(root);
    } catch {
      return;
    }
    if (!stats.isDirectory()) {
      return;
    }

    visit(root);
    if (depth >= MAX_SCAN_DEPTH) {
      return;
    }

    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(root, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }
      if (SKIP_DIR_NAMES.has(entry.name)) {
        continue;
      }
      this._walkDirectories(path.join(root, entry.name), depth + 1, visit);
    }
  }

  private _isPathInside(parentPath: string, childPath: string): boolean {
    const relativePath = path.relative(parentPath, childPath);
    return relativePath === '' || (!relativePath.startsWith('..') && !path.isAbsolute(relativePath));
  }
}