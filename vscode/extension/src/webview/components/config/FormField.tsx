import React, { ChangeEvent } from 'react';

export interface FormFieldProps {
  label: string;
  name: string;
  type?: 'text' | 'number' | 'checkbox' | 'select' | 'textarea';
  value: any;
  onChange: (name: string, value: any) => void;
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  rows?: number;
}

export const FormField: React.FC<FormFieldProps> = ({
  label,
  name,
  type = 'text',
  value,
  onChange,
  options = [],
  placeholder = '',
  disabled = false,
  className = '',
  required = false,
  min,
  max,
  step,
  rows = 3
}) => {
  const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const target = e.target as HTMLInputElement;
    const newValue = type === 'checkbox' 
      ? target.checked 
      : type === 'number' 
        ? target.valueAsNumber 
        : target.value;
    
    onChange(name, newValue);
  };

  const fieldId = `field-${name}`;
  const baseClasses = 'w-full px-3 py-2 border rounded bg-editor-background text-foreground border-border';
  const inputClasses = `${baseClasses} ${className} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`;

  return (
    <div className={`mb-4 ${disabled ? 'opacity-70' : ''}`}>
      <label 
        htmlFor={fieldId}
        className="block text-sm font-medium mb-1 text-foreground"
      >
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      
      {type === 'select' ? (
        <select
          id={fieldId}
          name={name}
          value={value || ''}
          onChange={handleChange}
          disabled={disabled}
          className={`${inputClasses} pr-8`}
          required={required}
        >
          {options.map(option => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : type === 'textarea' ? (
        <textarea
          id={fieldId}
          name={name}
          value={value || ''}
          onChange={handleChange}
          placeholder={placeholder}
          disabled={disabled}
          className={`${inputClasses} min-h-[80px]`}
          required={required}
          rows={rows}
        />
      ) : (
        <input
          id={fieldId}
          name={name}
          type={type}
          checked={type === 'checkbox' ? Boolean(value) : undefined}
          value={type !== 'checkbox' ? (value || '') : undefined}
          onChange={handleChange}
          placeholder={placeholder}
          disabled={disabled}
          className={`${inputClasses} ${type === 'checkbox' ? 'w-auto' : ''}`}
          required={required}
          min={min}
          max={max}
          step={step}
        />
      )}
    </div>
  );
};

export default FormField;
