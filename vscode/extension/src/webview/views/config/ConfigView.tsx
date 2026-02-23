import React, { useEffect, useCallback, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, useConfig } from '../../contexts/ConfigContext.js';
import { DebugConfiguration } from '../../types/debug.js';
import '@vscode-elements/elements/dist/vscode-elements.js';

import { vscode } from '../../vscodeApi.js';

interface ConfigViewProps {
  initialConfig?: Partial<DebugConfiguration>;
  onSave?: (config: DebugConfiguration) => void;
  onCancel?: () => void;
}

const generateId = () => Math.random().toString(36).substr(2, 9);

const WIZARD_STEPS = [
  { id: 'basics', title: 'Basics' },
  { id: 'runtime', title: 'Runtime' },
  { id: 'debug', title: 'Debug Options' },
  { id: 'review', title: 'Review & Create' },
] as const;

type StepIndex = 0 | 1 | 2 | 3;

const ConfigViewContent: React.FC<ConfigViewProps> = ({ initialConfig = {}, onSave, onCancel }) => {
  const { config, updateConfig, validate } = useConfig();
  const [localErrors, setLocalErrors] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState<StepIndex>(0);
  const [targetKind, setTargetKind] = useState<'program' | 'module'>('program');

  // Local state for lists to maintain stable IDs and focus
  const [argsList, setArgsList] = useState<{ id: string, value: string }[]>([]);
  const [envList, setEnvList] = useState<{ id: string, key: string, value: string }[]>([]);
  const [modulePathsList, setModulePathsList] = useState<{ id: string, value: string }[]>([]);

  const initialConfigApplied = useRef(false);
  useEffect(() => {
    if (!initialConfigApplied.current && initialConfig && Object.keys(initialConfig).length > 0) {
      updateConfig(initialConfig as Partial<DebugConfiguration>);
      setTargetKind(initialConfig.module ? 'module' : 'program');
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
    const currentPaths = config?.moduleSearchPaths || [];
    const localPaths = modulePathsList.map((p) => p.value);
    if (JSON.stringify(currentPaths) !== JSON.stringify(localPaths)) {
      setModulePathsList(currentPaths.map((value) => ({ id: generateId(), value })));
    }
  }, [config?.moduleSearchPaths]); // eslint-disable-line react-hooks/exhaustive-deps

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
        setTargetKind(data.config.module ? 'module' : 'program');
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

  const updateField = <K extends keyof DebugConfiguration>(field: K, value: DebugConfiguration[K]) => {
    updateConfig({ [field]: value } as Partial<DebugConfiguration>);
  };

  const nextStep = () => {
    setStepIndex((current) => Math.min(current + 1, WIZARD_STEPS.length - 1) as StepIndex);
  };

  const previousStep = () => {
    setStepIndex((current) => Math.max(current - 1, 0) as StepIndex);
  };

  const stepErrorCount = Object.values(localErrors).reduce((sum, entries) => sum + entries.length, 0);

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

  const updateModulePaths = (newList: { id: string, value: string }[]) => {
    setModulePathsList(newList);
    updateConfig({ moduleSearchPaths: newList.map((entry) => entry.value).filter(Boolean) });
  };

  const renderBasicsStep = () => (
    <vscode-form-group>
      <vscode-label>Name</vscode-label>
      <vscode-textfield
        value={config?.name || ''}
        onInput={(e: any) => updateField('name', (e.target as HTMLInputElement).value)}
        placeholder="Configuration name"
      />

      <vscode-label>Request</vscode-label>
      <vscode-single-select
        value={config?.request || 'launch'}
        onChange={(e: any) => updateField('request', (e.target as HTMLSelectElement).value as DebugConfiguration['request'])}
      >
        <vscode-option value="launch">launch</vscode-option>
        <vscode-option value="attach">attach</vscode-option>
      </vscode-single-select>

      <vscode-label>Launch Target</vscode-label>
      <vscode-radio-group
        value={targetKind}
        onChange={(e: any) => {
          const value = (e.target as HTMLInputElement).value as 'program' | 'module';
          setTargetKind(value);
          if (value === 'program') {
            updateConfig({ module: '' });
          } else {
            updateConfig({ program: '' });
          }
        }}
      >
        <vscode-radio value="program">Python file (`program`)</vscode-radio>
        <vscode-radio value="module">Python module (`module`)</vscode-radio>
      </vscode-radio-group>

      {targetKind === 'program' ? (
        <>
          <vscode-label>Program</vscode-label>
          <vscode-textfield
            value={config?.program || ''}
            onInput={(e: any) => updateField('program', (e.target as HTMLInputElement).value)}
            placeholder="${file}"
          />
        </>
      ) : (
        <>
          <vscode-label>Module</vscode-label>
          <vscode-textfield
            value={config?.module || ''}
            onInput={(e: any) => updateField('module', (e.target as HTMLInputElement).value)}
            placeholder="package.module"
          />
        </>
      )}
    </vscode-form-group>
  );

  const renderRuntimeStep = () => (
    <vscode-form-group>
      <vscode-label>Working Directory</vscode-label>
      <vscode-textfield
        value={config?.cwd || ''}
        onInput={(e: any) => updateField('cwd', (e.target as HTMLInputElement).value)}
        placeholder="${workspaceFolder}"
      />

      <vscode-label>Virtual Environment Path (optional)</vscode-label>
      <vscode-textfield
        value={config?.venvPath || ''}
        onInput={(e: any) => updateField('venvPath', (e.target as HTMLInputElement).value)}
        placeholder=".venv"
      />

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
          <vscode-button secondary onClick={() => updateArgs(argsList.filter((_, i) => i !== idx))}>Remove</vscode-button>
        </div>
      ))}
      <vscode-button secondary onClick={() => updateArgs([...argsList, { id: generateId(), value: '' }])}>Add Argument</vscode-button>

      {targetKind === 'module' && (
        <>
          <vscode-label>Module Search Paths</vscode-label>
          {modulePathsList.map((entry, idx) => (
            <div key={entry.id} className="form-row">
              <vscode-textfield
                value={entry.value}
                onInput={(e: any) => {
                  const v = (e.target as HTMLInputElement).value;
                  const next = [...modulePathsList];
                  next[idx] = { ...next[idx], value: v };
                  updateModulePaths(next);
                }}
              />
              <vscode-button secondary onClick={() => updateModulePaths(modulePathsList.filter((_, i) => i !== idx))}>Remove</vscode-button>
            </div>
          ))}
          <vscode-button secondary onClick={() => updateModulePaths([...modulePathsList, { id: generateId(), value: '' }])}>Add Search Path</vscode-button>
        </>
      )}

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
          <vscode-button secondary onClick={() => updateEnv(envList.filter((_, i) => i !== idx))}>Remove</vscode-button>
        </div>
      ))}
      <vscode-button secondary onClick={() => updateEnv([...envList, { id: generateId(), key: '', value: '' }])}>Add Environment Variable</vscode-button>
    </vscode-form-group>
  );

  const renderDebugStep = () => (
    <vscode-form-group>
      <vscode-label>Debug Server Port</vscode-label>
      <vscode-textfield
        type="number"
        value={String(config?.debugServer ?? 4711)}
        onInput={(e: any) => updateField('debugServer', Number((e.target as HTMLInputElement).value || 4711))}
      />

      <vscode-label>IPC Transport</vscode-label>
      <vscode-single-select
        value={config?.ipcTransport || 'pipe'}
        onChange={(e: any) => updateField('ipcTransport', (e.target as HTMLSelectElement).value as DebugConfiguration['ipcTransport'])}
      >
        <vscode-option value="pipe">pipe</vscode-option>
        <vscode-option value="tcp">tcp</vscode-option>
        <vscode-option value="unix">unix</vscode-option>
      </vscode-single-select>

      <vscode-checkbox checked={Boolean(config?.useIpc)} onChange={(e: any) => updateField('useIpc', (e.target as HTMLInputElement).checked)}>
        Use IPC
      </vscode-checkbox>
      <vscode-checkbox checked={Boolean(config?.frameEval)} onChange={(e: any) => updateField('frameEval', (e.target as HTMLInputElement).checked)}>
        Enable Frame Evaluation
      </vscode-checkbox>
      <vscode-checkbox checked={Boolean(config?.stopOnEntry)} onChange={(e: any) => updateField('stopOnEntry', (e.target as HTMLInputElement).checked)}>
        Stop on Entry
      </vscode-checkbox>
      <vscode-checkbox checked={Boolean(config?.justMyCode)} onChange={(e: any) => updateField('justMyCode', (e.target as HTMLInputElement).checked)}>
        Just My Code
      </vscode-checkbox>
      <vscode-checkbox checked={Boolean(config?.subprocessAutoAttach)} onChange={(e: any) => updateField('subprocessAutoAttach', (e.target as HTMLInputElement).checked)}>
        Auto-attach subprocesses
      </vscode-checkbox>
    </vscode-form-group>
  );

  const renderReviewStep = () => {
    const finalConfig = {
      ...config,
      type: 'dapper',
      request: config?.request || 'launch',
    };

    return (
      <vscode-form-group>
        <vscode-label>Review</vscode-label>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>
          {JSON.stringify(finalConfig, null, 2)}
        </pre>
      </vscode-form-group>
    );
  };

  const renderCurrentStep = () => {
    switch (stepIndex) {
      case 0:
        return renderBasicsStep();
      case 1:
        return renderRuntimeStep();
      case 2:
        return renderDebugStep();
      default:
        return renderReviewStep();
    }
  };

  return (
    <div className="config-view" style={{ padding: '16px' }}>
      {status && <div className="status">{status}</div>}

      <vscode-label style={{ display: 'block', marginBottom: '8px' }}>
        Step {stepIndex + 1} of {WIZARD_STEPS.length}: {WIZARD_STEPS[stepIndex].title}
      </vscode-label>
      <vscode-progress-ring value={((stepIndex + 1) / WIZARD_STEPS.length) * 100} />

      <form onSubmit={(e) => { e.preventDefault(); handleSave(e); }}>
        {renderCurrentStep()}

        {!!stepErrorCount && (
          <vscode-form-helper>
            {stepErrorCount} validation issue(s) detected. Review required fields before saving.
          </vscode-form-helper>
        )}

        <div className="form-actions">
          <vscode-button secondary disabled={stepIndex === 0} onClick={(e: React.MouseEvent) => { e.preventDefault(); previousStep(); }}>
            Back
          </vscode-button>

          {stepIndex < WIZARD_STEPS.length - 1 ? (
            <vscode-button onClick={(e: React.MouseEvent) => { e.preventDefault(); nextStep(); }}>
              Next
            </vscode-button>
          ) : (
            <vscode-button type="submit">Save Configuration</vscode-button>
          )}

          <vscode-button
            appearance="primary"
            onClick={(e) => {
              e.preventDefault();
              if (vscode) vscode.postMessage({ command: 'startDebug', config });
            }}
          >
            Start Debugging
          </vscode-button>
          <vscode-button
            secondary
            onClick={(e) => {
              e.preventDefault();
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

const rootElement = document.getElementById('root');
if (rootElement) {
  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <ConfigView />
    </React.StrictMode>
  );
}

export default ConfigView;
