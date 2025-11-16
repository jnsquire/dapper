import * as vscode from 'vscode';

export interface PythonEnvironment {
  path: string;
  version: string;
  env: NodeJS.ProcessEnv;
  pythonPath: string;
}

export class PythonEnvironmentManager {
  private static async getPythonExtension() {
    const pythonExtension = vscode.extensions.getExtension('ms-python.python');
    if (!pythonExtension) {
      throw new Error('Python extension is not installed');
    }
    if (!pythonExtension.isActive) {
      await pythonExtension.activate();
    }
    return pythonExtension;
  }

  public static async getPythonEnvironment(workspaceFolder?: vscode.WorkspaceFolder): Promise<PythonEnvironment> {
    try {
      const pythonExtension = await this.getPythonExtension();
      const api = pythonExtension.exports;
      
      // Get the Python interpreter details
      const interpreter = await api.environments.resolveEnvironment(
        workspaceFolder ? workspaceFolder.uri : undefined
      );

      if (!interpreter) {
        throw new Error('No Python interpreter found');
      }

      // Get environment variables for the interpreter
      const env = await interpreter.envVars;
      
      return {
        path: interpreter.path,
        version: interpreter.version?.major + '.' + interpreter.version?.minor,
        env: env || {},
        pythonPath: interpreter.path
      };
    } catch (error) {
      console.error('Failed to get Python environment:', error);
      throw error;
    }
  }

  public static async getDebugLaunchConfig(
    program: string,
    args: string[] = [],
    env: NodeJS.ProcessEnv = {},
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<vscode.DebugConfiguration> {
    const pythonEnv = await this.getPythonEnvironment(workspaceFolder);
    
    return {
      name: 'Python: Dapper Debug',
      type: 'python',
      request: 'launch',
      program,
      args,
      console: 'integratedTerminal',
      justMyCode: true,
      env: {
        ...pythonEnv.env,
        ...env,
        PYTHONPATH: [
          '${workspaceFolder}',
          pythonEnv.env.PYTHONPATH || ''
        ].filter(Boolean).join(':')
      },
      python: pythonEnv.pythonPath,
      pythonPath: pythonEnv.pythonPath
    };
  }

  public static async getDebugAdapterProcessArgs(
    program: string,
    args: string[] = [],
    env: NodeJS.ProcessEnv = {},
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<{ command: string; args: string[]; options: { env: NodeJS.ProcessEnv; cwd?: string } }> {
    const pythonEnv = await this.getPythonEnvironment(workspaceFolder);
    
    // Prepare the command and arguments for the debug adapter
    const debugArgs = [
      '-m', 'debugpy', '--listen', '0',
      '--wait-for-client',
      program,
      ...args
    ];

    return {
      command: pythonEnv.pythonPath,
      args: debugArgs,
      options: {
        env: {
          ...process.env,
          ...pythonEnv.env,
          ...env,
          PYTHONPATH: [
            '${workspaceFolder}',
            pythonEnv.env.PYTHONPATH || ''
          ].filter(Boolean).join(':')
        },
        cwd: workspaceFolder?.uri.fsPath
      }
    };
  }
}
