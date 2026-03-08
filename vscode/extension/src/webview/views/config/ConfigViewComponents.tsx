import React from 'react';

export interface ConfigWizardStep {
  id: string;
  title: string;
  description: string;
}

export interface StringListItem {
  id: string;
  value: string;
}

export interface KeyValueListItem {
  id: string;
  key: string;
  value: string;
}

interface SectionTitleProps {
  children: React.ReactNode;
}

export const SectionTitle: React.FC<SectionTitleProps> = ({ children }) => (
  <p className="step-section-title">{children}</p>
);

interface FieldProps {
  label: React.ReactNode;
  required?: boolean;
  hint?: React.ReactNode;
  children: React.ReactNode;
}

export const Field: React.FC<FieldProps> = ({ label, required = false, hint, children }) => (
  <div className="field">
    <vscode-label>
      {label}
      {required && <span className="field-required">*</span>}
    </vscode-label>
    {children}
    {hint && <div className="field-hint">{hint}</div>}
  </div>
);

interface WarningBannerProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export const WarningBanner: React.FC<WarningBannerProps> = ({ children, style }) => (
  <div className="wizard-error-banner" style={style}>
    {children}
  </div>
);

interface EditableStringListFieldProps {
  items: StringListItem[];
  emptyText: string;
  addLabel: string;
  placeholder: (index: number) => string;
  hint: React.ReactNode;
  onChange: (items: StringListItem[]) => void;
  createItem: () => StringListItem;
}

export const EditableStringListField: React.FC<EditableStringListFieldProps> = ({
  items,
  emptyText,
  addLabel,
  placeholder,
  hint,
  onChange,
  createItem,
}) => (
  <div className="field">
    <div className="list-section">
      {items.length === 0 && <div className="list-section-empty">{emptyText}</div>}
      {items.map((item, index) => (
        <div key={item.id} className="list-row">
          <vscode-textfield
            value={item.value}
            placeholder={placeholder(index)}
            onInput={(event: any) => {
              const nextItems = [...items];
              nextItems[index] = {
                ...nextItems[index],
                value: (event.target as HTMLInputElement).value,
              };
              onChange(nextItems);
            }}
          />
          <vscode-button
            type="button"
            secondary
            onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))}
          >
            ×
          </vscode-button>
        </div>
      ))}
      <div className="list-add-row">
        <vscode-button type="button" secondary onClick={() => onChange([...items, createItem()])}>
          {addLabel}
        </vscode-button>
      </div>
    </div>
    <div className="field-hint">{hint}</div>
  </div>
);

interface EditableKeyValueListFieldProps {
  items: KeyValueListItem[];
  emptyText: string;
  addLabel: string;
  keyPlaceholder: string;
  valuePlaceholder: string;
  hint: React.ReactNode;
  onChange: (items: KeyValueListItem[]) => void;
  createItem: () => KeyValueListItem;
}

export const EditableKeyValueListField: React.FC<EditableKeyValueListFieldProps> = ({
  items,
  emptyText,
  addLabel,
  keyPlaceholder,
  valuePlaceholder,
  hint,
  onChange,
  createItem,
}) => (
  <div className="field">
    <div className="list-section">
      {items.length === 0 && <div className="list-section-empty">{emptyText}</div>}
      {items.map((item, index) => (
        <div key={item.id} className="list-row">
          <vscode-textfield
            className="list-row-key"
            style={{ flex: '0 0 36%' }}
            value={item.key}
            placeholder={keyPlaceholder}
            onInput={(event: any) => {
              const nextItems = [...items];
              nextItems[index] = {
                ...nextItems[index],
                key: (event.target as HTMLInputElement).value,
              };
              onChange(nextItems);
            }}
          />
          <vscode-textfield
            value={item.value}
            placeholder={valuePlaceholder}
            onInput={(event: any) => {
              const nextItems = [...items];
              nextItems[index] = {
                ...nextItems[index],
                value: (event.target as HTMLInputElement).value,
              };
              onChange(nextItems);
            }}
          />
          <vscode-button
            type="button"
            secondary
            onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))}
          >
            ×
          </vscode-button>
        </div>
      ))}
      <div className="list-add-row">
        <vscode-button type="button" secondary onClick={() => onChange([...items, createItem()])}>
          {addLabel}
        </vscode-button>
      </div>
    </div>
    <div className="field-hint">{hint}</div>
  </div>
);

interface CheckboxFieldProps {
  checked: boolean;
  label: React.ReactNode;
  hint: React.ReactNode;
  onChange: (checked: boolean) => void;
}

export const CheckboxField: React.FC<CheckboxFieldProps> = ({ checked, label, hint, onChange }) => (
  <div className="checkbox-row">
    <vscode-checkbox checked={checked} onChange={(event: any) => onChange((event.target as HTMLInputElement).checked)}>
      {label}
    </vscode-checkbox>
    <div className="field-hint">{hint}</div>
  </div>
);

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
        <vscode-button onClick={onUseConfiguration}>✓ Use this configuration</vscode-button>
      ) : (
        <>
          <vscode-button secondary onClick={onSaveDefault}>
            Save as Default
          </vscode-button>
          <vscode-button secondary onClick={onStartDebugging}>
            ▶ Start Debugging
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
