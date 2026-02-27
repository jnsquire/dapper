import React, { useEffect, useCallback, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, useConfig } from '../../contexts/ConfigContext.js';
import { DebugConfiguration } from '../../types/debug.js';
// vscode-elements is loaded as a separate <script> tag in the webview HTML

import { vscode } from '../../vscodeApi.js';

interface ConfigViewProps {
  initialConfig?: Partial<DebugConfiguration>;
  onSave?: (config: DebugConfiguration) => void;
  onCancel?: () => void;
}

const generateId = () => Math.random().toString(36).substr(2, 9);

const WIZARD_STEPS = [
  { id: 'basics',  title: 'Basics',          description: 'Name your configuration and choose what to launch.' },
  { id: 'runtime', title: 'Runtime',         description: 'Set the working directory, arguments, and environment.' },
  { id: 'debug',   title: 'Debug Options',   description: 'Configure the debug adapter and Python-specific options.' },
  { id: 'review',  title: 'Review & Create', description: 'Verify your settings, then save or start debugging.' },
] as const;

type StepIndex = 0 | 1 | 2 | 3;

const ConfigViewContent: React.FC<ConfigViewProps> = ({ initialConfig = {}, onSave, onCancel }) => {
  const { config, updateConfig, validate } = useConfig();
  const [localErrors, setLocalErrors] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState<StepIndex>(0);
  /** True when the wizard was opened by the Dynamic debug-config provider. */
  const [providerMode, setProviderMode] = useState(false);
  // Local state for lists to maintain stable IDs and focus
  const [argsList, setArgsList] = useState<{ id: string, value: string }[]>([]);
  const [envList, setEnvList] = useState<{ id: string, key: string, value: string }[]>([]);
  const [modulePathsList, setModulePathsList] = useState<{ id: string, value: string }[]>([]);

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
  // Only reset when config changes externally; ignore blank in-progress rows in the comparison.
  useEffect(() => {
    const currentConfigEnv = config?.env || {};
    const committedLocalEnv = envList
      .filter(e => e.key.trim())
      .reduce((acc, curr) => ({ ...acc, [curr.key]: curr.value }), {} as Record<string, string>);

    const configKeys = Object.keys(currentConfigEnv).sort();
    const localKeys = Object.keys(committedLocalEnv).sort();
    const keysMatch = JSON.stringify(configKeys) === JSON.stringify(localKeys);
    const valuesMatch = keysMatch && configKeys.every(k => currentConfigEnv[k] === committedLocalEnv[k]);

    if (!valuesMatch) {
      setEnvList(Object.entries(currentConfigEnv).map(([k, v]) => ({ id: generateId(), key: k, value: v as string })));
    }
  }, [config?.env]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const currentPaths = config?.moduleSearchPaths || [];
    // Ignore blank in-progress rows when comparing
    const committedLocalPaths = modulePathsList.map(p => p.value).filter(Boolean);
    if (JSON.stringify(currentPaths) !== JSON.stringify(committedLocalPaths)) {
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
        if (data.providerMode) setProviderMode(true);
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
    <>
      <p className="step-section-title">Identity</p>

      <div className="field">
        <vscode-label>
          Configuration Name <span className="field-required">*</span>
        </vscode-label>
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.name || ''}
          onInput={(e: any) => updateField('name', (e.target as HTMLInputElement).value)}
          placeholder="My Python App"
        />
        <div className="field-hint">Appears in the debug dropdown in the Run panel.</div>
      </div>

      <div className="field">
        <vscode-label>Request</vscode-label>
        <vscode-radio-group
          variant="vertical"
          onChange={(e: any) => updateField('request', (e.target as HTMLInputElement).value as DebugConfiguration['request'])}
        >
          <vscode-radio
            label="launch"
            name="request"
            value="launch"
            checked={!config?.request || config.request === 'launch'}
          />
          <vscode-radio
            label="attach"
            name="request"
            value="attach"
            checked={config?.request === 'attach'}
          />
        </vscode-radio-group>
        <div className="field-hint">
          {config?.request === 'attach'
            ? 'Connect to an already-running process via a debug port.'
            : 'Start a new Python process and attach the debugger immediately.'}
        </div>
      </div>

      <p className="step-section-title">Target</p>

      {!!(config?.program && config?.module) && (
        <div className="wizard-error-banner" style={{ marginBottom: '10px' }}>
          ⚠ Both <strong>Program</strong> and <strong>Module</strong> are set —
          <strong>Module takes priority</strong> and Program will be ignored.
          Clear Module if you want to run a file directly.
        </div>
      )}

      <div className="field">
        <vscode-label>Program path</vscode-label>
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.program || ''}
          onInput={(e: any) => updateField('program', (e.target as HTMLInputElement).value)}
          placeholder="${file}"
        />
        <div className="field-hint">
          Run a specific file. Absolute path or VS Code variable —
          e.g. <code>{'${file}'}</code> for the currently open file.
          Ignored if <strong>Module</strong> is also set.
        </div>
      </div>

      <div className="field">
        <vscode-label>Module name</vscode-label>
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.module || ''}
          onInput={(e: any) => updateField('module', (e.target as HTMLInputElement).value)}
          placeholder="package.module"
        />
        <div className="field-hint">
          Run as a module: equivalent to <code>python -m package.module</code>.
          Takes priority over Program when both are set.
          Leave blank to run the Program file directly.
        </div>
      </div>
    </>
  );

  const renderRuntimeStep = () => (
    <>
      <p className="step-section-title">Paths</p>

      <div className="field">
        <vscode-label>Working directory</vscode-label>
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.cwd || ''}
          onInput={(e: any) => updateField('cwd', (e.target as HTMLInputElement).value)}
          placeholder="${workspaceFolder}"
        />
        <div className="field-hint">Current directory when the process starts. Defaults to workspace root.</div>
      </div>

      <div className="field">
        <vscode-label>Virtual environment path</vscode-label>
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.venvPath || ''}
          onInput={(e: any) => updateField('venvPath', (e.target as HTMLInputElement).value)}
          placeholder=".venv"
        />
        <div className="field-hint">Relative or absolute path to a venv. Leave blank to use the workspace interpreter.</div>
      </div>

      <p className="step-section-title">Arguments</p>

      <div className="field">
        <div className="list-section">
          {argsList.length === 0 && (
            <div className="list-section-empty">No arguments — click Add to append one.</div>
          )}
          {argsList.map((arg, idx) => (
            <div key={arg.id} className="list-row">
              <vscode-textfield
                value={arg.value}
                placeholder={`arg ${idx + 1}`}
                onInput={(e: any) => {
                  const v = (e.target as HTMLInputElement).value;
                  const next = [...argsList];
                  next[idx] = { ...next[idx], value: v };
                  updateArgs(next);
                }}
              />
              <vscode-button type="button" secondary onClick={() => updateArgs(argsList.filter((_, i) => i !== idx))}>×</vscode-button>
            </div>
          ))}
          <div className="list-add-row">
            <vscode-button type="button" secondary onClick={() => updateArgs([...argsList, { id: generateId(), value: '' }])}>
              + Add argument
            </vscode-button>
          </div>
        </div>
        <div className="field-hint">Passed to the program as <code>sys.argv[1:]</code>.</div>
      </div>

      {!!(config?.module) && (
        <>
          <p className="step-section-title">Module search paths</p>
          <div className="field">
            <div className="list-section">
              {modulePathsList.length === 0 && (
                <div className="list-section-empty">No extra paths — click Add to append one.</div>
              )}
              {modulePathsList.map((entry, idx) => (
                <div key={entry.id} className="list-row">
                  <vscode-textfield
                    value={entry.value}
                    placeholder="/path/to/dir"
                    onInput={(e: any) => {
                      const v = (e.target as HTMLInputElement).value;
                      const next = [...modulePathsList];
                      next[idx] = { ...next[idx], value: v };
                      updateModulePaths(next);
                    }}
                  />
                  <vscode-button type="button" secondary onClick={() => updateModulePaths(modulePathsList.filter((_, i) => i !== idx))}>×</vscode-button>
                </div>
              ))}
              <div className="list-add-row">
                <vscode-button type="button" secondary onClick={() => updateModulePaths([...modulePathsList, { id: generateId(), value: '' }])}>
                  + Add search path
                </vscode-button>
              </div>
            </div>
            <div className="field-hint">Extra directories prepended to <code>sys.path</code> when resolving the module.</div>
          </div>
        </>
      )}

      <p className="step-section-title">Environment variables</p>

      <div className="field">
        <div className="list-section">
          {envList.length === 0 && (
            <div className="list-section-empty">No environment overrides — click Add to define one.</div>
          )}
          {envList.map((entry, idx) => (
            <div key={entry.id} className="list-row">
              <vscode-textfield
                className="list-row-key"
                style={{ flex: '0 0 36%' }}
                value={entry.key}
                placeholder="NAME"
                onInput={(e: any) => {
                  const v = (e.target as HTMLInputElement).value;
                  const next = [...envList];
                  next[idx] = { ...next[idx], key: v };
                  updateEnv(next);
                }}
              />
              <vscode-textfield
                value={entry.value}
                placeholder="value"
                onInput={(e: any) => {
                  const v = (e.target as HTMLInputElement).value;
                  const next = [...envList];
                  next[idx] = { ...next[idx], value: v };
                  updateEnv(next);
                }}
              />
              <vscode-button type="button" secondary onClick={() => updateEnv(envList.filter((_, i) => i !== idx))}>×</vscode-button>
            </div>
          ))}
          <div className="list-add-row">
            <vscode-button type="button" secondary onClick={() => updateEnv([...envList, { id: generateId(), key: '', value: '' }])}>
              + Add variable
            </vscode-button>
          </div>
        </div>
        <div className="field-hint">Merged with the inherited environment of the VS Code process.</div>
      </div>
    </>
  );

  const renderDebugStep = () => (
    <>
      <p className="step-section-title">Transport</p>

      <div className="field">
        <vscode-label>IPC transport</vscode-label>
        <vscode-single-select
          style={{ width: '200px' }}
          value={config?.ipcTransport || 'pipe'}
          onChange={(e: any) => updateField('ipcTransport', (e.target as HTMLSelectElement).value as DebugConfiguration['ipcTransport'])}
        >
          <vscode-option value="pipe">pipe (recommended)</vscode-option>
          <vscode-option value="tcp">tcp</vscode-option>
          <vscode-option value="unix">unix socket</vscode-option>
        </vscode-single-select>
        <div className="field-hint">
          Communication channel between VS Code and the debug adapter.
          <strong> pipe</strong> and <strong>unix</strong> use a local socket;
          <strong> tcp</strong> requires a port number below.
        </div>
      </div>

      {config?.ipcTransport === 'tcp' && (
        <div className="field">
          <vscode-label>Debug server port</vscode-label>
          <vscode-textfield
            style={{ width: '120px' }}
            type="number"
            value={String(config?.debugServer ?? 4711)}
            onInput={(e: any) => updateField('debugServer', Number((e.target as HTMLInputElement).value || 4711))}
          />
          <div className="field-hint">Port the debug adapter listens on when using TCP transport (default 4711).</div>
        </div>
      )}

      <p className="step-section-title">Execution behaviour</p>

      <div className="checkbox-group">
        <div className="checkbox-row">
          <vscode-checkbox checked={Boolean(config?.frameEval)} onChange={(e: any) => updateField('frameEval', (e.target as HTMLInputElement).checked)}>
            Enable frame evaluation
          </vscode-checkbox>
          <div className="field-hint">Dapper's low-overhead frame evaluator — improves performance during heavy stepping.</div>
        </div>
        <div className="checkbox-row">
          <vscode-checkbox checked={Boolean(config?.stopOnEntry)} onChange={(e: any) => updateField('stopOnEntry', (e.target as HTMLInputElement).checked)}>
            Stop on entry
          </vscode-checkbox>
          <div className="field-hint">Break on the very first statement before any user code runs.</div>
        </div>
        <div className="checkbox-row">
          <vscode-checkbox checked={Boolean(config?.justMyCode)} onChange={(e: any) => updateField('justMyCode', (e.target as HTMLInputElement).checked)}>
            Just My Code
          </vscode-checkbox>
          <div className="field-hint">Skip stepping into standard library and third-party packages.</div>
        </div>
      </div>

      <p className="step-section-title">Subprocess debugging</p>

      <div className="checkbox-group">
        <div className="checkbox-row">
          <vscode-checkbox checked={Boolean(config?.subprocessAutoAttach)} onChange={(e: any) => updateField('subprocessAutoAttach', (e.target as HTMLInputElement).checked)}>
            Auto-attach to subprocesses
          </vscode-checkbox>
          <div className="field-hint">Automatically attach the debugger to any child processes spawned at runtime.</div>
        </div>
      </div>
    </>
  );

  const renderReviewStep = () => {
    const finalConfig = {
      ...config,
      type: 'dapper',
      request: config?.request || 'launch',
    };

    return (
      <vscode-form-group>
        <pre className="review-json">
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
    <div className="wizard-shell">

      {/* ── Step rail ─────────────────────────────────────────── */}
      <ol className="wizard-rail">
        {WIZARD_STEPS.map((step, idx) => {
          const cls = idx < stepIndex ? 'done' : idx === stepIndex ? 'active' : '';
          return (
            <li key={step.id} className={cls}>
              <div className="step-circle">
                {idx < stepIndex ? '✓' : idx + 1}
              </div>
              <span className="step-label">{step.title}</span>
            </li>
          );
        })}
      </ol>

      {/* ── Scrollable content card ────────────────────────────── */}
      <form
        className="wizard-body"
        onSubmit={(e) => { e.preventDefault(); handleSave(e); }}
      >
        <div className="step-header">
          <h2>{WIZARD_STEPS[stepIndex].title}</h2>
          <p>{WIZARD_STEPS[stepIndex].description}</p>
        </div>

        <div className="step-fields">
          {renderCurrentStep()}
        </div>

        {!!stepErrorCount && (
          <div className="wizard-error-banner">
            ⚠&nbsp;{stepErrorCount} validation issue{stepErrorCount > 1 ? 's' : ''} — review required fields before saving.
          </div>
        )}

        {status && <div className="wizard-status">{status}</div>}
      </form>

      {/* ── Sticky footer ──────────────────────────────────────── */}
      <div className="wizard-footer">
        <div className="wizard-footer-left">
          <vscode-button
            secondary
            disabled={stepIndex === 0}
            onClick={(e: React.MouseEvent) => { e.preventDefault(); previousStep(); }}
          >
            ← Back
          </vscode-button>
        </div>

        <div className="wizard-footer-right">
          {stepIndex < WIZARD_STEPS.length - 1 ? (
            <vscode-button
              onClick={(e: React.MouseEvent) => { e.preventDefault(); nextStep(); }}
            >
              Next →
            </vscode-button>
          ) : (
            <>
              {providerMode ? (
                /* Opened by the Dynamic debug-config provider — return the config to VS Code */
                <vscode-button
                  onClick={(e: React.MouseEvent) => {
                    e.preventDefault();
                    if (vscode) vscode.postMessage({ command: 'confirmConfig', config });
                  }}
                >
                  ✓ Use this configuration
                </vscode-button>
              ) : (
                <>
                  <vscode-button
                    secondary
                    onClick={(e: React.MouseEvent) => {
                      e.preventDefault();
                      if (vscode) vscode.postMessage({ command: 'saveAndInsert', config });
                    }}
                  >
                    Save to launch.json
                  </vscode-button>
                  <vscode-button
                    secondary
                    onClick={(e: React.MouseEvent) => {
                      e.preventDefault();
                      if (vscode) vscode.postMessage({ command: 'startDebug', config });
                    }}
                  >
                    ▶ Start Debugging
                  </vscode-button>
                  <vscode-button
                    onClick={(e: React.MouseEvent) => { e.preventDefault(); handleSave(e); }}
                  >
                    Save Configuration
                  </vscode-button>
                </>
              )}
            </>
          )}
          <vscode-button
            secondary
            onClick={(e: React.MouseEvent) => { e.preventDefault(); handleCancel(e); }}
          >
            Cancel
          </vscode-button>
        </div>
      </div>

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
