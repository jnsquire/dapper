import * as React from 'react';
import * as ReactDOM from 'react-dom/client';
import { VariableInspector } from '../ui/components/VariableInspector.js';

// Get initial state from the HTML
const initialState = (window as any).initialProps || { variables: [] };

// Find the root element
const rootElement = document.getElementById('root');
if (rootElement) {
  // Create a root
  const root = ReactDOM.createRoot(rootElement);
  
  // Initial render
  root.render(
    <React.StrictMode>
      <VariableInspector {...initialState} />
    </React.StrictMode>
  );

  // Handle messages from the extension
  window.addEventListener('message', event => {
    const message = event.data;
    switch (message.type) {
      case 'updateVariables':
        root.render(
          <React.StrictMode>
            <VariableInspector variables={message.variables} />
          </React.StrictMode>
        );
        break;
      // Add more message types as needed
    }
  });
}

// Notify the extension that the webview is ready
const vscode = acquireVsCodeApi();
vscode.postMessage({
  type: 'ready'
});
