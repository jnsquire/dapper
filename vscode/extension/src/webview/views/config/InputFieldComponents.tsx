import React from 'react';
import { Field } from './FieldComponents.js';

interface TextInputFieldProps {
  label: React.ReactNode;
  value: string;
  onValueChange: (value: string) => void;
  required?: boolean;
  hint?: React.ReactNode;
  placeholder?: string;
  style?: React.CSSProperties;
  type?: 'text' | 'number';
}

export const TextInputField: React.FC<TextInputFieldProps> = ({
  label,
  value,
  onValueChange,
  required = false,
  hint,
  placeholder,
  style = { width: '100%' },
  type = 'text',
}) => (
  <Field label={label} required={required} hint={hint}>
    <vscode-textfield
      style={style}
      type={type}
      value={value}
      placeholder={placeholder}
      onInput={(event: any) => onValueChange((event.target as HTMLInputElement).value)}
    />
  </Field>
);

interface NumberInputFieldProps {
  label: React.ReactNode;
  value: number | undefined;
  onValueChange: (value: number | undefined) => void;
  hint?: React.ReactNode;
  placeholder?: string;
  style?: React.CSSProperties;
  emptyValue?: number;
}

export const NumberInputField: React.FC<NumberInputFieldProps> = ({
  label,
  value,
  onValueChange,
  hint,
  placeholder,
  style = { width: '120px' },
  emptyValue,
}) => (
  <Field label={label} hint={hint}>
    <vscode-textfield
      style={style}
      type="number"
      value={value == null ? '' : String(value)}
      placeholder={placeholder}
      onInput={(event: any) => {
        const rawValue = (event.target as HTMLInputElement).value;
        if (rawValue === '') {
          onValueChange(emptyValue);
          return;
        }
        onValueChange(Number(rawValue));
      }}
    />
  </Field>
);

interface SingleSelectFieldProps {
  label: React.ReactNode;
  value: string;
  onValueChange: (value: string) => void;
  hint?: React.ReactNode;
  style?: React.CSSProperties;
  children: React.ReactNode;
}

export const SingleSelectField: React.FC<SingleSelectFieldProps> = ({
  label,
  value,
  onValueChange,
  hint,
  style,
  children,
}) => (
  <Field label={label} hint={hint}>
    <vscode-single-select
      style={style}
      value={value}
      onChange={(event: any) => onValueChange((event.target as HTMLSelectElement).value)}
    >
      {children}
    </vscode-single-select>
  </Field>
);

interface RadioGroupFieldProps {
  label: React.ReactNode;
  hint?: React.ReactNode;
  onValueChange: (value: string) => void;
  variant?: 'vertical' | 'horizontal';
  children: React.ReactNode;
}

export const RadioGroupField: React.FC<RadioGroupFieldProps> = ({
  label,
  hint,
  onValueChange,
  variant = 'vertical',
  children,
}) => (
  <Field label={label} hint={hint}>
    <vscode-radio-group
      variant={variant}
      onChange={(event: any) => onValueChange((event.target as HTMLInputElement).value)}
    >
      {children}
    </vscode-radio-group>
  </Field>
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
