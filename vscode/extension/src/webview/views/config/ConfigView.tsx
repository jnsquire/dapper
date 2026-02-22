import React, { useEffect, useCallback, useState, useRef } from 'react';
import { ConfigProvider, useConfig } from '../../contexts/ConfigContext.js';
import { DebugConfiguration } from '../../types/debug.js';
import { useWebComponentEvents } from '../../hooks/useWebComponentEvents.js';
import '@vscode-elements/elements/dist/vscode-elements.js';

import { vscode } from '../../vscodeApi.js';

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

const generateId = () => Math.random().toString(36).substr(2, 9);

const ConfigViewContent: React.FC<ConfigViewProps> = ({ initialConfig = {}, onSave, onCancel, isSubProcess = false }) => {
  const { config, updateConfig, validate } = useConfig();
  const [localErrors, setLocalErrors] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<string | null>(null);

  // Local state for lists to maintain stable IDs and focus
  const [argsList, setArgsList] = useState<{ id: string, value: string }[]>([]);
  const [envList, setEnvList] = useState<{ id: string, key: string, value: string }[]>([]);

  // Handlers from the hook to wire webcomponent events to config updates
  const { createInputHandler, createCheckboxHandler } = useWebComponentEvents<DebugConfiguration>(
    (field, value) => updateConfig({ [field]: value } as Partial<DebugConfiguration>)
  );

  const initialConfigApplied = useRef(false);
  useEffect(() => {
    if (!initialConfigApplied.current && initialConfig && Object.keys(initialConfig).length > 0) {
      updateConfig(initialConfig as Partial<DebugConfiguration>);
      initialConfigApplied.current = true;
    }
    // Request config from host in case it's provided asynchronously
    if (vscode) vscode.postMessage({ command: 'requestConfig' });
  }, [initialConfig, updateConfig]);

  // Sync Config -> Local State (Args)
  useEffect(() => {
    const currentConfigArgs = config?.args || [];
    const currentLocalArgs = argsList.map(a => a.value);
    if (JSON.stringify(currentConfigArgs) !== JSON.stringify(currentLocalArgs)) {
      setArgsList(currentConfigArgs.map(a => ({ id: generateId(), value: a })));
    }
  }, [config?.args]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync Config -> Local State (Env)
  useEffect(() => {
    const currentConfigEnv = config?.env || {};
    const currentLocalEnvObj = envList.reduce((acc, curr) => ({ ...acc, [curr.key]: curr.value }), {} as Record<string, string>);
    
    const configKeys = Object.keys(currentConfigEnv).sort();
    const localKeys = Object.keys(currentLocalEnvObj).sort();
    const keysMatch = JSON.stringify(configKeys) === JSON.stringify(localKeys);
    const valuesMatch = keysMatch && configKeys.every(k => currentConfigEnv[k] === currentLocalEnvObj[k]);

    if (!valuesMatch) {
      setEnvList(Object.entries(currentConfigEnv).map(([k, v]) => ({ id: generateId(), key: k, value: v as string })));
    }
  }, [config?.env]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const updateArgs = (newList: { id: string, value: string }[]) => {
    setArgsList(newList);
    updateConfig({ args: newList.map(a => a.value) });
  };

  const updateEnv = (newList: { id: string, key: string, value: string }[]) => {
    setEnvList(newList);
    const newEnv = newList.reduce((acc, curr) => {
      if (curr.key) acc[curr.key] = curr.value;
      return acc;
    }, {} as Record<string, string>);
    updateConfig({ env: newEnv });
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
            {argsList.map((arg, idx) => (
              <div key={arg.id} className="form-row">
                <vscode-textfield
                  value={arg.value}
                  onInput={(e: any) => {
                    const v = (e.target as HTMLInputElement).value;
                    const next = [...argsList];
                    next[idx] = { ...next[idx], value: v };
                    updateArgs(next);
                  }}
                />
                <vscode-button
                  {...({ appearance: 'icon' } as any)}
                  onClick={() => updateArgs(argsList.filter((_, i) => i !== idx))}
                >
                  <span slot="start" className="codicon codicon-remove" />
                </vscode-button>
              </div>
            ))}
            <vscode-button icon="add" secondary onClick={() => updateArgs([...argsList, { id: generateId(), value: '' }])}>Add Argument</vscode-button>
          </vscode-form-group>

          <vscode-form-group>
            <vscode-label>Environment Variables</vscode-label>
            {envList.map((entry, idx) => (
              <div key={entry.id} className="form-row">
                <vscode-textfield
                  value={entry.key}
                  onInput={(e: any) => {
                    const v = (e.target as HTMLInputElement).value;
                    const next = [...envList];
                    next[idx] = { ...next[idx], key: v };
                    updateEnv(next);
                  }}
                  placeholder="Name"
                />
                <vscode-textfield
                  value={entry.value}
                  onInput={(e: any) => {
                    const v = (e.target as HTMLInputElement).value;
                    const next = [...envList];
                    next[idx] = { ...next[idx], value: v };
                    updateEnv(next);
                  }}
                  placeholder="Value"
                />
                <vscode-button icon="remove" onClick={() => updateEnv(envList.filter((_, i) => i !== idx))}>
                </vscode-button>
              </div>
            ))}
            <vscode-button secondary onClick={() => updateEnv([...envList, { id: generateId(), key: 'NEW_VAR_' + Date.now(), value: '' }])}>
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
