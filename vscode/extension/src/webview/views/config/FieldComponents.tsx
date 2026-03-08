import React from 'react';


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
