import * as React from 'react';
import { useState, useEffect } from 'react';
import * as ReactDOM from 'react-dom/client';
import { VariableInspector } from '../ui/components/VariableInspector.js';
import { vscode } from './vscodeApi.js';

// Get initial state from the HTML
const initialState = (window as any).initialProps || { variables: [] };

const App: React.FC = () => {
  const [variables, setVariables] = useState(initialState.variables);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const message = event.data;
      switch (message.type) {
        case 'updateVariables':
          setVariables(message.variables);
          break;
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  return <VariableInspector variables={variables} />;
};

// Find the root element
const rootElement = document.getElementById('root');
if (rootElement) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

// Notify the extension that the webview is ready
vscode?.postMessage({ type: 'ready' });
