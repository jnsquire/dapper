// NOTE: Always use @vscode-elements/elements for UI components in webviews
// instead of @vscode/webview-ui-toolkit
import React, { useState, useEffect } from 'react';

// Declare the acquireVsCodeApi function
declare function acquireVsCodeApi(): {
  postMessage(message: any): void;
  getState(): any;
  setState(state: any): void;
};

const vscode = acquireVsCodeApi();

interface DebugConfiguration {
  name: string;
  type: string;
  request: string;
  program: string;
  args: string[];
  cwd: string;
  debugServer: number;
  useIpc: boolean;
  ipcTransport: 'tcp' | 'unix' | 'pipe';
  frameEval: boolean;
  inProcess: boolean;
  stopOnEntry: boolean;
  justMyCode: boolean;
}

export const DebugConfigWebview: React.FC = () => {
  const [config, setConfig] = useState<DebugConfiguration>({
    name: 'Dapper Debug',
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
  });

  const handleSave = () => {
    vscode.postMessage({
      command: 'saveConfig',
      config: config
    });
  };

  const handleChange = (field: keyof DebugConfiguration, value: any) => {
    setConfig(prev => ({
      ...prev,
      [field]: value
    }));
  };

  return (
    <div className="debug-config-container" style={{ padding: '20px', fontFamily: 'var(--vscode-font-family)' }}>
      <h2 style={{ marginTop: '0' }}>Dapper Debug Configuration</h2>
      
      <div className="form-group" style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>Name</label>
        <vscode-textfield 
          value={config.name}
          onInput={(e: any) => handleChange('name', e.target.value)}
          style={{ width: '100%' }}
        />
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>Program</label>
        <vscode-textfield 
          value={config.program}
          onInput={(e: any) => handleChange('program', e.target.value)}
          style={{ width: '100%' }}
        />
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>Working Directory</label>
        <vscode-textfield 
          value={config.cwd}
          onInput={(e: any) => handleChange('cwd', e.target.value)}
          style={{ width: '100%' }}
        />
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>Debug Server Port</label>
        <vscode-textfield 
          type="number"
          value={config.debugServer.toString()}
          onInput={(e: any) => handleChange('debugServer', parseInt(e.target.value, 10))}
          style={{ width: '100%' }}
        />
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <vscode-checkbox 
          checked={config.useIpc}
          onInput={(e: any) => handleChange('useIpc', e.target.checked)}
        >
          Use IPC
        </vscode-checkbox>
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <vscode-checkbox 
          checked={config.frameEval}
          onInput={(e: any) => handleChange('frameEval', e.target.checked)}
        >
          Enable Frame Evaluation
        </vscode-checkbox>
      </div>

      <div className="form-group" style={{ marginBottom: '15px' }}>
        <vscode-checkbox 
          checked={config.stopOnEntry}
          onInput={(e: any) => handleChange('stopOnEntry', e.target.checked)}
        >
          Stop on Entry
        </vscode-checkbox>
      </div>

      <div className="form-group" style={{ marginBottom: '20px' }}>
        <vscode-checkbox 
          checked={config.justMyCode}
          onInput={(e: any) => handleChange('justMyCode', e.target.checked)}
        >
          Just My Code
        </vscode-checkbox>
      </div>

      <div className="actions">
        <vscode-button 
          onClick={handleSave} 
          style={{ marginRight: '10px' }}
          appearance="primary"
        >
          Save Configuration
        </vscode-button>
        <vscode-button 
          onClick={() => vscode.postMessage({ command: 'cancelConfig' })} 
          appearance="secondary"
        >
          Cancel
        </vscode-button>
      </div>
    </div>
  );
};

export default DebugConfigWebview;
