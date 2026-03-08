import React, { useEffect, useCallback, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, useConfig } from '../../contexts/ConfigContext.js';
import { DebugConfiguration } from '../../types/debug.js';
import {
  CheckboxField,
  EditableKeyValueListField,
  EditableStringListField,
  Field,
  type KeyValueListItem,
  SectionTitle,
  StepHeader,
  type StringListItem,
  WarningBanner,
  WizardFooter,
  WizardRail,
} from './ConfigViewComponents.js';
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
  const [argsList, setArgsList] = useState<StringListItem[]>([]);
  const [envList, setEnvList] = useState<KeyValueListItem[]>([]);
  const [modulePathsList, setModulePathsList] = useState<StringListItem[]>([]);

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

  const createStringListItem = (value = ''): StringListItem => ({ id: generateId(), value });
  const createKeyValueListItem = (key = '', value = ''): KeyValueListItem => ({ id: generateId(), key, value });

  const updateArgs = (newList: StringListItem[]) => {
    setArgsList(newList);
    updateConfig({ args: newList.map(a => a.value) });
  };

  const updateEnv = (newList: KeyValueListItem[]) => {
    setEnvList(newList);
    const newEnv = newList.reduce((acc, curr) => {
      if (curr.key) acc[curr.key] = curr.value;
      return acc;
    }, {} as Record<string, string>);
    updateConfig({ env: newEnv });
  };

  const updateModulePaths = (newList: StringListItem[]) => {
    setModulePathsList(newList);
    updateConfig({ moduleSearchPaths: newList.map((entry) => entry.value).filter(Boolean) });
  };

  const renderBasicsStep = () => (
    <>
      <SectionTitle>Identity</SectionTitle>

      <Field
        label="Configuration Name "
        required
        hint="Appears in the debug dropdown in the Run panel."
      >
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.name || ''}
          onInput={(e: any) => updateField('name', (e.target as HTMLInputElement).value)}
          placeholder="My Python App"
        />
      </Field>

      <Field
        label="Request"
        hint={
          config?.request === 'attach'
            ? 'Attach either by PID or by connecting to an existing debug adapter host/port.'
            : 'Start a new Python process and attach the debugger immediately.'
        }
      >
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
      </Field>

      <SectionTitle>Target</SectionTitle>

        {config?.request !== 'attach' && !!(config?.program && config?.module) && (
        <WarningBanner style={{ marginBottom: '10px' }}>
            ⚠ Both <strong>Program</strong> and <strong>Module</strong> are set.
            Choose exactly one launch target before saving or starting the session.
        </WarningBanner>
      )}

        {config?.request === 'attach' && !!(config?.processId && config?.host && config?.port) && (
          <WarningBanner style={{ marginBottom: '10px' }}>
            ⚠ Both <strong>processId</strong> and <strong>host/port</strong> are set.
            Choose exactly one attach target before saving or starting the session.
          </WarningBanner>
        )}

        {config?.request !== 'attach' && (
        <Field
          label="Program path"
          hint={
            <>
              Run a specific file. Absolute path or VS Code variable — e.g. <code>{'${file}'}</code> for the currently open file.
              Leave <strong>Module</strong> blank when launching a file directly.
            </>
          }
        >
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.program || ''}
          onInput={(e: any) => updateField('program', (e.target as HTMLInputElement).value)}
          placeholder="${file}"
        />
      </Field>
      )}

      {config?.request !== 'attach' && (
      <Field
        label="Module name"
        hint={
          <>
            Run as a module: equivalent to <code>python -m package.module</code>.
            Leave <strong>Program path</strong> blank when launching a module.
          </>
        }
      >
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.module || ''}
          onInput={(e: any) => updateField('module', (e.target as HTMLInputElement).value)}
          placeholder="package.module"
        />
      </Field>
      )}

      {config?.request === 'attach' && (
        <>
          <Field
            label="Process ID"
            hint="Attach to a local process by PID. Leave host/port empty when using this mode."
          >
            <vscode-textfield
              style={{ width: '100%' }}
              value={config?.processId == null ? '' : String(config.processId)}
              onInput={(e: any) => updateField('processId', (e.target as HTMLInputElement).value)}
              placeholder="${command:pickProcess}"
            />
          </Field>

          <Field
            label="Host"
            hint="Host name of an already-running DAP endpoint. Leave Process ID empty when using host/port."
          >
            <vscode-textfield
              style={{ width: '100%' }}
              value={config?.host || ''}
              onInput={(e: any) => updateField('host', (e.target as HTMLInputElement).value)}
              placeholder="localhost"
            />
          </Field>

          <Field
            label="Port"
            hint="TCP port of the remote debug adapter. Requires Host when using host/port attach."
          >
            <vscode-textfield
              style={{ width: '120px' }}
              type="number"
              value={config?.port == null ? '' : String(config.port)}
              onInput={(e: any) => {
                const value = (e.target as HTMLInputElement).value;
                updateField('port', value === '' ? undefined : Number(value));
              }}
              placeholder="5678"
            />
          </Field>
        </>
      )}
    </>
  );

  const renderRuntimeStep = () => (
    <>
      <SectionTitle>Paths</SectionTitle>

      <Field
        label="Working directory"
        hint="Current directory when the process starts. Defaults to workspace root."
      >
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.cwd || ''}
          onInput={(e: any) => updateField('cwd', (e.target as HTMLInputElement).value)}
          placeholder="${workspaceFolder}"
        />
      </Field>

      <Field
        label="Virtual environment path"
        hint="Relative or absolute path to a venv. Leave blank to use the workspace interpreter."
      >
        <vscode-textfield
          style={{ width: '100%' }}
          value={config?.venvPath || ''}
          onInput={(e: any) => updateField('venvPath', (e.target as HTMLInputElement).value)}
          placeholder=".venv"
        />
      </Field>

      <SectionTitle>Arguments</SectionTitle>

      <EditableStringListField
        items={argsList}
        emptyText="No arguments — click Add to append one."
        addLabel="+ Add argument"
        placeholder={(index: number) => `arg ${index + 1}`}
        hint={<>Passed to the program as <code>sys.argv[1:]</code>.</>}
        onChange={updateArgs}
        createItem={() => createStringListItem()}
      />

      {config?.request !== 'attach' && !!(config?.module) && (
        <>
          <SectionTitle>Module search paths</SectionTitle>
          <EditableStringListField
            items={modulePathsList}
            emptyText="No extra paths — click Add to append one."
            addLabel="+ Add search path"
            placeholder={() => '/path/to/dir'}
            hint={<>Extra directories prepended to <code>sys.path</code> when resolving the module.</>}
            onChange={updateModulePaths}
            createItem={() => createStringListItem()}
          />
        </>
      )}

      <SectionTitle>Environment variables</SectionTitle>

      <EditableKeyValueListField
        items={envList}
        emptyText="No environment overrides — click Add to define one."
        addLabel="+ Add variable"
        keyPlaceholder="NAME"
        valuePlaceholder="value"
        hint="Merged with the inherited environment of the VS Code process."
        onChange={updateEnv}
        createItem={() => createKeyValueListItem()}
      />
    </>
  );

  const renderDebugStep = () => (
    <>
      <SectionTitle>Transport</SectionTitle>

      <Field
        label="IPC transport"
        hint={
          <>
            Communication channel between VS Code and the debug adapter.
            <strong> pipe</strong> and <strong>unix</strong> use a local socket;
            <strong> tcp</strong> requires a port number below.
          </>
        }
      >
        <vscode-single-select
          style={{ width: '200px' }}
          value={config?.ipcTransport || 'pipe'}
          onChange={(e: any) => updateField('ipcTransport', (e.target as HTMLSelectElement).value as DebugConfiguration['ipcTransport'])}
        >
          <vscode-option value="pipe">pipe (recommended)</vscode-option>
          <vscode-option value="tcp">tcp</vscode-option>
          <vscode-option value="unix">unix socket</vscode-option>
        </vscode-single-select>
      </Field>

      {config?.ipcTransport === 'tcp' && (
        <Field
          label="Debug server port"
          hint="Port the debug adapter listens on when using TCP transport (default 4711)."
        >
          <vscode-textfield
            style={{ width: '120px' }}
            type="number"
            value={String(config?.debugServer ?? 4711)}
            onInput={(e: any) => updateField('debugServer', Number((e.target as HTMLInputElement).value || 4711))}
          />
        </Field>
      )}

      <SectionTitle>Execution behaviour</SectionTitle>

      <div className="checkbox-group">
        <CheckboxField
          checked={Boolean(config?.frameEval)}
          label="Enable frame evaluation"
          hint="Dapper's low-overhead frame evaluator — improves performance during heavy stepping."
          onChange={(checked: boolean) => updateField('frameEval', checked)}
        />
        <CheckboxField
          checked={Boolean(config?.stopOnEntry)}
          label="Stop on entry"
          hint="Break on the very first statement before any user code runs."
          onChange={(checked: boolean) => updateField('stopOnEntry', checked)}
        />
        <CheckboxField
          checked={Boolean(config?.justMyCode)}
          label="Just My Code"
          hint="Skip stepping into standard library and third-party packages."
          onChange={(checked: boolean) => updateField('justMyCode', checked)}
        />
      </div>

      <SectionTitle>Subprocess debugging</SectionTitle>

      <div className="checkbox-group">
        <CheckboxField
          checked={Boolean(config?.subprocessAutoAttach)}
          label="Auto-attach to subprocesses"
          hint="Automatically attach the debugger to any child processes spawned at runtime."
          onChange={(checked: boolean) => updateField('subprocessAutoAttach', checked)}
        />
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
      <WizardRail steps={WIZARD_STEPS} stepIndex={stepIndex} />

      <form
        className="wizard-body"
        onSubmit={(e) => { e.preventDefault(); handleSave(e); }}
      >
        <StepHeader title={WIZARD_STEPS[stepIndex].title} description={WIZARD_STEPS[stepIndex].description} />

        <div className="step-fields">
          {renderCurrentStep()}
        </div>

        {!!stepErrorCount && (
          <WarningBanner>
            ⚠&nbsp;{stepErrorCount} validation issue{stepErrorCount > 1 ? 's' : ''} — review required fields before saving.
          </WarningBanner>
        )}

        {status && <div className="wizard-status">{status}</div>}
      </form>

      <WizardFooter
        canGoBack={stepIndex > 0}
        isLastStep={stepIndex === WIZARD_STEPS.length - 1}
        providerMode={providerMode}
        onBack={(e: React.MouseEvent) => { e.preventDefault(); previousStep(); }}
        onNext={(e: React.MouseEvent) => { e.preventDefault(); nextStep(); }}
        onUseConfiguration={(e: React.MouseEvent) => {
          e.preventDefault();
          if (vscode) vscode.postMessage({ command: 'confirmConfig', config });
        }}
        onSaveDefault={(e: React.MouseEvent) => {
          e.preventDefault();
          if (vscode) vscode.postMessage({ command: 'saveConfig', config });
        }}
        onStartDebugging={(e: React.MouseEvent) => {
          e.preventDefault();
          if (vscode) vscode.postMessage({ command: 'startDebug', config });
        }}
        onSaveToLaunchJson={(e: React.MouseEvent) => {
          e.preventDefault();
          if (vscode) vscode.postMessage({ command: 'saveAndInsert', config });
        }}
        onCancel={(e: React.MouseEvent) => { e.preventDefault(); handleCancel(e); }}
      />
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
