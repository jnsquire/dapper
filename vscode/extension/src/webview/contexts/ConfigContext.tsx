import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { DebugConfiguration } from '../types/debug.js';
import { validateConfig, sanitizeConfig, mergeWithDefaults } from '../utils/configValidation.js';

interface ConfigContextType {
  config: DebugConfiguration;
  updateConfig: (updates: Partial<DebugConfiguration>) => void;
  validate: () => { valid: boolean; errors: string[] };
  reset: () => void;
  errors: string[];
}

const ConfigContext = createContext<ConfigContextType | undefined>(undefined);

interface ConfigProviderProps {
  children: ReactNode;
  initialConfig?: Partial<DebugConfiguration>;
  onConfigChange?: (config: DebugConfiguration) => void;
}

export const ConfigProvider: React.FC<ConfigProviderProps> = ({ 
  children, 
  initialConfig = {},
  onConfigChange 
}) => {
  const [config, setConfig] = useState<DebugConfiguration>(() => 
    mergeWithDefaults({ ...initialConfig, name: initialConfig.name || 'Dapper Debug' })
  );
  const [errors, setErrors] = useState<string[]>([]);

  const updateConfig = useCallback((updates: Partial<DebugConfiguration>) => {
    setConfig(prev => {
      const newConfig = sanitizeConfig({
        ...prev,
        ...updates
      });
      
      // Notify parent component of changes
      if (onConfigChange) {
        onConfigChange(newConfig);
      }
      
      // Validate the new configuration
      const { errors: validationErrors } = validateConfig(newConfig);
      setErrors(validationErrors);
      
      return newConfig;
    });
  }, [onConfigChange]);

  const validate = useCallback(() => {
    const { valid, errors: validationErrors } = validateConfig(config);
    setErrors(validationErrors);
    return { valid, errors: validationErrors };
  }, [config]);

  const reset = useCallback(() => {
    const defaultConfig = mergeWithDefaults({});
    setConfig(defaultConfig);
    setErrors([]);
    
    if (onConfigChange) {
      onConfigChange(defaultConfig);
    }
  }, [onConfigChange]);

  return (
    <ConfigContext.Provider 
      value={{
        config,
        updateConfig,
        validate,
        reset,
        errors
      }}
    >
      {children}
    </ConfigContext.Provider>
  );
};

export const useConfig = (): ConfigContextType => {
  const context = useContext(ConfigContext);
  if (context === undefined) {
    throw new Error('useConfig must be used within a ConfigProvider');
  }
  return context;
};
