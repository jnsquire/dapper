import { useEffect, useRef, useState } from 'react';
import { DebugConfiguration } from '../types/debug.js';
import { vscode } from '../vscodeApi.js';

interface UseWizardHostSyncOptions {
  config: DebugConfiguration;
  initialConfig: Partial<DebugConfiguration>;
  updateConfig: (updates: Partial<DebugConfiguration>) => void;
}

interface UseWizardHostSyncResult {
  providerMode: boolean;
  status: string | null;
}

export function useWizardHostSync({
  config,
  initialConfig,
  updateConfig,
}: UseWizardHostSyncOptions): UseWizardHostSyncResult {
  const [providerMode, setProviderMode] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const initialConfigApplied = useRef(false);
  const hasLoadedHostConfig = useRef(false);

  useEffect(() => {
    const listener = (ev: MessageEvent) => {
      const data = ev.data as {
        command?: string;
        config?: Partial<DebugConfiguration>;
        providerMode?: boolean;
        text?: string;
      };

      if (data.command === 'updateConfig' && data.config) {
        hasLoadedHostConfig.current = true;
        updateConfig(data.config);
        if (data.providerMode) {
          setProviderMode(true);
        }
        return;
      }

      if (data.command === 'updateStatus' && data.text) {
        setStatus(String(data.text));
      }
    };

    window.addEventListener('message', listener);

    if (!initialConfigApplied.current && Object.keys(initialConfig).length > 0) {
      updateConfig(initialConfig);
      initialConfigApplied.current = true;
    }

    vscode?.postMessage({ command: 'requestConfig' });

    return () => window.removeEventListener('message', listener);
  }, [initialConfig, updateConfig]);

  useEffect(() => {
    if (!hasLoadedHostConfig.current) {
      return;
    }

    vscode?.postMessage({ command: 'draftConfigChanged', config });
  }, [config]);

  useEffect(() => {
    if (!status) {
      return;
    }

    const id = setTimeout(() => setStatus(null), 4000);
    return () => clearTimeout(id);
  }, [status]);

  return { providerMode, status };
}