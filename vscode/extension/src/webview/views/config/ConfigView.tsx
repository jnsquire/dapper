import React, { useEffect, useCallback, useState } from 'react';
import { ConfigProvider, useConfig } from '../../contexts/ConfigContext.js';
import { DebugConfiguration } from '../../types/debug.js';
import { useWebComponentEvents } from '../../hooks/useWebComponentEvents.js';
import '@vscode-elements/elements/dist/vscode-elements.js';

// Declare the acquireVsCodeApi function (VS Code webview API)
declare function acquireVsCodeApi(): {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
};

declare global {
  interface Window {
    vscode: ReturnType<typeof acquireVsCodeApi> | undefined;
  }
}

const vscode = typeof acquireVsCodeApi !== 'undefined' ? acquireVsCodeApi() : undefined;

type VSCodeComponentProps = {
  id?: string;
  value?: string | number | boolean;
  checked?: boolean;
  onInput?: (e: Event) => void;
  onChange?: (e: Event) => void;
  onClick?: (e: Event) => void;
  'data-vscode-context'?: string;
  className?: string;
  [key: string]: unknown;
};

interface ConfigViewProps {
  initialConfig?: Partial<DebugConfiguration>;
  onSave?: (config: DebugConfiguration) => void;
  onCancel?: () => void;
  isSubProcess?: boolean;
}

const ConfigViewContent: React.FC<ConfigViewProps> = ({ initialConfig = {}, onSave, onCancel, isSubProcess = false }) => {
  const { config, updateConfig, validate } = useConfig();
  const [localErrors, setLocalErrors] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<string | null>(null);

  // Handlers from the hook to wire webcomponent events to config updates
  const { createInputHandler, createCheckboxHandler } = useWebComponentEvents<DebugConfiguration>(
    (field, value) => updateConfig({ [field]: value } as Partial<DebugConfiguration>)
  );

  useEffect(() => {
    if (initialConfig && Object.keys(initialConfig).length > 0) {
      updateConfig(initialConfig as Partial<DebugConfiguration>);
    }
    // Request config from host in case it's provided asynchronously
    if (vscode) vscode.postMessage({ command: 'requestConfig' });
  }, [initialConfig, updateConfig]);

  useEffect(() => {
    const { valid, errors } = validate();
    if (!valid && errors) {
      const grouped = errors.reduce<Record<string, string[]>>((acc, e) => {
        const s = String(e);
        const match = s.match(/^([^:]+):/);
        const key = match ? match[1].trim() : 'general';
        acc[key] = acc[key] || [];
        acc[key].push(s);
        return acc;
      }, {});
      setLocalErrors(grouped);
    } else {
      setLocalErrors({});
    }
  }, [config, validate]);

  // Message listener for updates from the extension host
  useEffect(() => {
    const listener = (ev: MessageEvent) => {
      const data = ev.data as any;
      if (data?.command === 'updateConfig' && data.config) {
        updateConfig(data.config as Partial<DebugConfiguration>);
      } else if (data?.command === 'updateStatus' && data.text) {
        setStatus(String((data as any).text));
      }
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [updateConfig]);

  // Clear ephemeral status messages after a short timeout
  useEffect(() => {
    if (!status) return;
    const id = setTimeout(() => setStatus(null), 4000);
    return () => clearTimeout(id);
  }, [status]);

  const handleSave = useCallback((e?: React.FormEvent) => {
    e?.preventDefault();
    const { valid } = validate();
    if (valid) {
      if (onSave) onSave(config as DebugConfiguration);
      else if (vscode) vscode.postMessage({ command: 'saveConfig', config });
    }
  }, [config, onSave, validate]);

  const handleCancel = useCallback((e?: React.MouseEvent) => {
    e?.preventDefault();
    if (onCancel) onCancel();
    else if (vscode) vscode.postMessage({ command: 'cancelConfig' });
  }, [onCancel]);

  const getFieldProps = <K extends keyof DebugConfiguration>(field: K, type: 'text' | 'checkbox' = 'text'): VSCodeComponentProps => {
    const value = config?.[field];
    const error = localErrors[String(field)]?.[0];
    const base: VSCodeComponentProps = {
      id: String(field),
      'data-vscode-context': JSON.stringify({ field }),
      className: error ? 'error' : ''
    };
    if (type === 'checkbox') {
      return {
        ...base,
        checked: Boolean(value),
        onChange: createCheckboxHandler(field as any)
      };
    }
    return {
      ...base,
      value: value == null ? '' : String(value),
      onInput: createInputHandler(field as any)
    };
  };

  return (
    <div className="config-view">
      {status && <div className="status">{status}</div>}
      <form onSubmit={(e) => { e.preventDefault(); handleSave(e); }}>
        <vscode-form-group>
          <vscode-label>Name</vscode-label>
          <vscode-textfield {...(getFieldProps('name') as any)} placeholder="Configuration name">
          </vscode-textfield>

          <vscode-label>Program</vscode-label>
          <vscode-textfield {...(getFieldProps('program') as any)} placeholder="Path to your program">
          </vscode-textfield>

          <vscode-label>Working Directory</vscode-label>
          <vscode-textfield {...(getFieldProps('cwd') as any)} placeholder="Working directory">
          </vscode-textfield>

          <vscode-form-group>
            <vscode-label>Arguments</vscode-label>
            {(Array.isArray(config?.args) ? config!.args! : []).map((arg, idx) => (
              <div key={idx} className="form-row">
                <vscode-textfield
                  value={String(arg)}
                  onInput={(e: any) => {
                    const v = (e.target as HTMLInputElement).value;
                    const next = [...(config?.args || [])];
                    next[idx] = v;
                    updateConfig({ args: next });
                  }}
                />
                <vscode-button
                  {...({ appearance: 'icon' } as any)}
                  onClick={() => updateConfig({ args: (config?.args || []).filter((_, i) => i !== idx) })}
                >
                  <span slot="start" className="codicon codicon-remove" />
                </vscode-button>
              </div>
            ))}
            <vscode-button icon="add" secondary onClick={() => updateConfig({ args: [...(config?.args || []), ''] })}>Add Argument</vscode-button>
          </vscode-form-group>

          <vscode-form-group>
            <vscode-label>Environment Variables</vscode-label>
            {Object.entries(config?.env || {}).map(([k, v]) => (
              <div key={k} className="form-row">
                <vscode-textfield
                  value={k}
                  onInput={(e: any) => {
                    const newKey = (e.target as HTMLInputElement).value;
                    const env = { ...(config?.env || {}) };
                    delete env[k];
                    env[newKey] = v;
                    updateConfig({ env });
                  }}
                  placeholder="Name"
                />
                <vscode-textfield
                  value={String(v)}
                  onInput={(e: any) => updateConfig({ env: { ...(config?.env || {}), [k]: (e.target as HTMLInputElement).value } })}
                  placeholder="Value"
                />
                <vscode-button icon="remove" onClick={() => {
                  const newEnv = { ...(config?.env || {}) } as Record<string, string>;
                  delete newEnv[k];
                  updateConfig({ env: newEnv });
                }}>
                </vscode-button>
              </div>
            ))}
            <vscode-button secondary onClick={() => updateConfig({ env: { ...(config?.env || {}), ['NEW_VAR_' + Date.now()]: '' } })}>
              <span slot="start" className="codicon codicon-add" />Add Environment Variable
            </vscode-button>
          </vscode-form-group>
        </vscode-form-group>

        <div className="form-actions">
          <vscode-button type="submit">Save Configuration</vscode-button>
          <vscode-button
            appearance="primary"
            onClick={(e) => {
              e.preventDefault();
              // Start debugging with current config
              if (vscode) vscode.postMessage({ command: 'startDebug', config });
            }}
          >
            Start Debugging
          </vscode-button>
          <vscode-button
            secondary
            onClick={(e) => {
              e.preventDefault();
              // save and insert into launch.json
              if (vscode) vscode.postMessage({ command: 'saveAndInsert', config });
            }}
          >
            Save & Insert to launch.json
          </vscode-button>
          <vscode-button secondary onClick={(e) => { e.preventDefault(); handleCancel(e); }}>Cancel</vscode-button>
        </div>
      </form>
    </div>
  );
};

const ConfigView: React.FC<ConfigViewProps> = (props) => (
  <ConfigProvider initialConfig={props.initialConfig || {}}>
    <ConfigViewContent {...props} />
  </ConfigProvider>
);

export default ConfigView;
