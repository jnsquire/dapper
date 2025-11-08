import React, { useCallback } from 'react';
import '../../types/vscode-elements.d';
import '@vscode-elements/elements/dist/vscode-elements.js';

interface EnvironmentVariablesProps {
  variables: Record<string, string>;
  onChange: (variables: Record<string, string>) => void;
  className?: string;
}

export const EnvironmentVariables: React.FC<EnvironmentVariablesProps> = ({
  variables = {},
  onChange,
  className = ''
}) => {
  const handleAddVariable = useCallback(() => {
    const newVars = { ...variables, '': '' };
    onChange(newVars);
  }, [variables, onChange]);

  const handleRemoveVariable = useCallback((key: string) => {
    const newVars = { ...variables };
    delete newVars[key];
    onChange(newVars);
  }, [variables, onChange]);

  const handleVariableChange = useCallback((oldKey: string, newKey: string, value: string) => {
    const newVars = { ...variables };
    
    // If the key changed, remove the old entry
    if (oldKey !== newKey) {
      delete newVars[oldKey];
    }
    
    // Only add if key is not empty
    if (newKey) {
      newVars[newKey] = value;
    }
    
    onChange(newVars);
  }, [variables, onChange]);

  return (
    <div className={className}>
      <vscode-form-group label="Environment Variables">
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          marginBottom: '12px'
        }}>
          <vscode-button 
            appearance="secondary"
            onClick={handleAddVariable}
            style={{ '--button-padding-horizontal': '12px' } as React.CSSProperties}
          >
            <span slot="start" className="codicon codicon-add" style={{ fontSize: '14px' }}></span>
            Add Variable
          </vscode-button>
        </div>
        
        <div style={{
          display: 'grid',
          gap: '8px',
          marginBottom: '8px'
        }}>
          {Object.entries(variables).map(([key, value]) => (
            <vscode-form-item key={key}>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr auto',
                gap: '8px',
                alignItems: 'center'
              }}>
                <vscode-text-field 
                  placeholder="Variable name"
                  value={key}
                  onInput={(e: any) => handleVariableChange(key, e.target.value, value)}
                  style={{ width: '100%' }}
                />
                <vscode-text-field 
                  placeholder="Value"
                  value={value}
                  onInput={(e: any) => handleVariableChange(key, key, e.target.value)}
                  style={{ width: '100%' }}
                />
                <vscode-button
                  icon="trash"
                  onClick={(e) => {
                    e.preventDefault();
                    handleRemoveVariable(key);
                  }}
                  aria-label={`Remove ${key}`}
                  style={{
                    '--button-icon-size': '16px',
                    '--button-size': '32px',
                    '--button-icon-color': 'var(--vscode-foreground)'
                  } as React.CSSProperties}
                />
              </div>
            </vscode-form-item>
          ))}
          
          {Object.keys(variables).length === 0 && (
            <vscode-form-description style={{
              textAlign: 'center',
              padding: '16px',
              color: 'var(--vscode-descriptionForeground)',
              fontSize: '13px',
              border: '1px dashed var(--vscode-panel-border)',
              borderRadius: '4px'
            }}>
              No environment variables defined. Click "Add Variable" to add one.
            </vscode-form-description>
          )}
        </div>
      </vscode-form-group>
    </div>
  );
};

export default EnvironmentVariables;
