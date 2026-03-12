import React, { useEffect, useCallback, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, useConfig } from '../contexts/ConfigContext.js';
import { DebugConfiguration } from '../types/debug.js';
import {
  StepHeader,
  WarningBanner,
  WizardFooter,
  WizardRail,
} from '../components/ConfigViewComponents.js';
import { useRuntimeLists } from '../hooks/useRuntimeLists.js';
import { useWizardHostSync } from '../hooks/useWizardHostSync.js';
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
  const [stepIndex, setStepIndex] = useState<StepIndex>(0);
  const { providerMode, status } = useWizardHostSync({ config, initialConfig, updateConfig });
  const {
    argsList,
    envList,
    modulePathsList,
    updateArgs,
    updateEnv,
    updateModulePaths,
    createStringListItem,
    createKeyValueListItem,
  } = useRuntimeLists(config, updateConfig);

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

  const stepContent = [
    <BasicsStep key="basics" config={config} updateField={updateField} />,
    (
      <RuntimeStep
        key="runtime"
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
    ),
    <DebugStep key="debug" config={config} updateField={updateField} />,
    <ReviewStep key="review" config={config} />,
  ] as const;

  return (
    <div className="wizard-shell">
      <WizardRail steps={WIZARD_STEPS} stepIndex={stepIndex} />

      <form
        className="wizard-body"
        onSubmit={(e) => { e.preventDefault(); handleSave(e); }}
      >
        <StepHeader title={WIZARD_STEPS[stepIndex].title} description={WIZARD_STEPS[stepIndex].description} />

        <div className="step-fields">
          {stepContent[stepIndex]}
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
        onSaveAndLaunch={(e: React.MouseEvent) => {
          e.preventDefault();
          if (vscode) vscode.postMessage({ command: 'saveAndLaunch', config });
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
