import React from 'react';

export interface ConfigWizardStep {
  id: string;
  title: string;
  description: string;
}

interface WizardRailProps {
  steps: readonly ConfigWizardStep[];
  stepIndex: number;
}

export const WizardRail: React.FC<WizardRailProps> = ({ steps, stepIndex }) => (
  <ol className="wizard-rail">
    {steps.map((step, index) => {
      const className = index < stepIndex ? 'done' : index === stepIndex ? 'active' : '';
      return (
        <li key={step.id} className={className}>
          <div className="step-circle">{index < stepIndex ? '✓' : index + 1}</div>
          <span className="step-label">{step.title}</span>
        </li>
      );
    })}
  </ol>
);

interface StepHeaderProps {
  title: string;
  description: string;
}

export const StepHeader: React.FC<StepHeaderProps> = ({ title, description }) => (
  <div className="step-header">
    <h2>{title}</h2>
    <p>{description}</p>
  </div>
);

interface WizardFooterProps {
  canGoBack: boolean;
  isLastStep: boolean;
  providerMode: boolean;
  onBack: (event: React.MouseEvent) => void;
  onNext: (event: React.MouseEvent) => void;
  onUseConfiguration: (event: React.MouseEvent) => void;
  onSaveDefault: (event: React.MouseEvent) => void;
  onStartDebugging: (event: React.MouseEvent) => void;
  onSaveAndLaunch: (event: React.MouseEvent) => void;
  onSaveToLaunchJson: (event: React.MouseEvent) => void;
  onCancel: (event: React.MouseEvent) => void;
}

export const WizardFooter: React.FC<WizardFooterProps> = ({
  canGoBack,
  isLastStep,
  providerMode,
  onBack,
  onNext,
  onUseConfiguration,
  onSaveDefault,
  onStartDebugging,
  onSaveAndLaunch,
  onSaveToLaunchJson,
  onCancel,
}) => (
  <div className="wizard-footer">
    <div className="wizard-footer-left">
      <vscode-button secondary disabled={!canGoBack} onClick={onBack}>
        ← Back
      </vscode-button>
    </div>

    <div className="wizard-footer-right">
      {!isLastStep ? (
        <vscode-button onClick={onNext}>Next →</vscode-button>
      ) : providerMode ? (
        <>
          <vscode-button secondary onClick={onSaveToLaunchJson}>
            Save to launch.json
          </vscode-button>
          <vscode-button secondary onClick={onSaveAndLaunch}>
            Save and Launch
          </vscode-button>
          <vscode-button onClick={onUseConfiguration}>✓ Use this configuration</vscode-button>
        </>
      ) : (
        <>
          <vscode-button secondary onClick={onSaveDefault}>
            Save as Default
          </vscode-button>
          <vscode-button secondary onClick={onStartDebugging}>
            ▶ Start Debugging
          </vscode-button>
          <vscode-button secondary onClick={onSaveAndLaunch}>
            Save and Launch
          </vscode-button>
          <vscode-button onClick={onSaveToLaunchJson}>Save to launch.json</vscode-button>
        </>
      )}
      <vscode-button secondary onClick={onCancel}>
        Cancel
      </vscode-button>
    </div>
  </div>
);
