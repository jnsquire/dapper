import React, { useEffect, useCallback, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, useConfig } from '../contexts/ConfigContext.js';
import { DebugConfiguration } from '../types/debug.js';
import {
  type KeyValueListItem,
  StepHeader,
  type StringListItem,
  WarningBanner,
  WizardFooter,
  WizardRail,
} from '../components/ConfigViewComponents.js';
import {
  BasicsStep,
  DebugStep,
  ReviewStep,
  RuntimeStep,
} from './ConfigViewSteps.js';
// vscode-elements is loaded as a separate <script> tag in the webview HTML

import { vscode } from '../vscodeApi.js';

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
      setArgsList(currentConfigArgs.map((a: string) => ({ id: generateId(), value: a })));
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
      setModulePathsList(currentPaths.map((value: string) => ({ id: generateId(), value })));
    }
  }, [config?.moduleSearchPaths]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const { valid, errors } = validate();
    if (!valid && errors) {
      const grouped = errors.reduce<Record<string, string[]>>((acc: Record<string,string[]>, e: any) => {
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

  const renderCurrentStep = () => {
    switch (stepIndex) {
      case 0:
        return <BasicsStep config={config} updateField={updateField} />;
      case 1:
        return (
          <RuntimeStep
            config={config}
            updateField={updateField}
            argsList={argsList}
            envList={envList}
            modulePathsList={modulePathsList}
            updateArgs={updateArgs}
            updateEnv={updateEnv}
            updateModulePaths={updateModulePaths}
            createStringListItem={createStringListItem}
            createKeyValueListItem={createKeyValueListItem}
          />
        );
      case 2:
        return <DebugStep config={config} updateField={updateField} />;
      default:
        return <ReviewStep config={config} />;
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
