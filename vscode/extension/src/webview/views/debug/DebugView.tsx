import React from 'react';

interface DebugViewProps {
  onStartDebugging: () => void;
  onSetBreakpoint: (file: string, line: number) => void;
  onInspectVariable: (variableName: string) => void;
}

export const DebugView: React.FC<DebugViewProps> = ({
  onStartDebugging,
  onSetBreakpoint,
  onInspectVariable
}) => {
  return (
    <div className="debug-container">
      <div className="toolbar">
        <vscode-button 
          id="start-debugging" 
          appearance="primary" 
          title="Start Debugging (F5)"
          onClick={onStartDebugging}
        >
          <span slot="start" className="codicon codicon-debug-start"></span>
          Start
        </vscode-button>
        <vscode-button id="pause" appearance="secondary" disabled title="Pause (F6)">
          <span slot="start" className="codicon codicon-debug-pause"></span>
          Pause
        </vscode-button>
        <vscode-button id="step-over" appearance="secondary" disabled title="Step Over (F10)">
          <span slot="start" className="codicon codicon-debug-step-over"></span>
          Step Over
        </vscode-button>
        <vscode-button id="step-into" appearance="secondary" disabled title="Step Into (F11)">
          <span slot="start" className="codicon codicon-debug-step-into"></span>
          Step Into
        </vscode-button>
        <vscode-button id="step-out" appearance="secondary" disabled title="Step Out (Shift+F11)">
          <span slot="start" className="codicon codicon-debug-step-out"></span>
          Step Out
        </vscode-button>
      </div>
      <div className="debug-content">
        {/* Debug content will go here */}
      </div>
    </div>
  );
};

export default DebugView;
