import * as vscode from 'vscode';
import { getUri } from './utils';

export function getWebviewContent(
  webview: vscode.Webview, 
  extensionUri: vscode.Uri,
  viewType: 'debug' | 'config' = 'debug'
) {
  // Get URIs for resources
  const stylesUri = getUri(webview, extensionUri, ['webview', 'styles.css']);
  const elementsUri = 'https://unpkg.com/@vscode-elements/elements/dist/vscode-elements.js';

  // Use a nonce to only allow specific scripts to be run
  const nonce = getNonce();

  // Determine which content to show based on view type
  const title = viewType === 'config' ? 'Dapper Settings' : 'Dapper Debugger';
  const appScript = viewType === 'config' ? 'config.js' : 'app.js';

  return `<!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="
      default-src 'none';
      style-src ${webview.cspSource} 'unsafe-inline' https://unpkg.com;
      script-src 'nonce-${nonce}' https://unpkg.com;
      font-src ${webview.cspSource} https://unpkg.com;
      img-src ${webview.cspSource} https: data:;
    ">
    <link href="${stylesUri}" rel="stylesheet" />
    <script type="module" nonce="${nonce}" src="${elementsUri}"></script>
    <title>${title}</title>
  </head>
  <body>
    <div class="toolbar">
      <vscode-button id="start-debugging" appearance="icon" title="Start Debugging (F5)">
        <span slot="start" class="codicon codicon-debug-start"></span>
        Start
      </vscode-button>
      <vscode-button id="pause" appearance="icon" disabled title="Pause (F6)">
        <span slot="start" class="codicon codicon-debug-pause"></span>
        Pause
      </vscode-button>
      <vscode-button id="step-over" appearance="icon" disabled title="Step Over (F10)">
        <span slot="start" class="codicon codicon-debug-step-over"></span>
        Step Over
      </vscode-button>
      <vscode-button id="step-into" appearance="icon" disabled title="Step Into (F11)">
        <span slot="start" class="codicon codicon-debug-step-into"></span>
        Step Into
      </vscode-button>
      <vscode-button id="step-out" appearance="icon" disabled title="Step Out (Shift+F11)">
        <span slot="start" class="codicon codicon-debug-step-out"></span>
        Step Out
      </vscode-button>
      <vscode-button id="restart" appearance="icon" title="Restart (Ctrl+Shift+F5)">
        <span slot="start" class="codicon codicon-debug-restart"></span>
        Restart
      </vscode-button>
      <vscode-button id="stop" appearance="icon" title="Stop (Shift+F5)">
        <span slot="start" class="codicon codicon-debug-stop"></span>
        Stop
      </vscode-button>
    </div>

    <vscode-panels>
      <vscode-panel-tab id="tab-variables">
        <span slot="start" class="codicon codicon-symbol-variable"></span>
        Variables
      </vscode-panel-tab>
      <vscode-panel-tab id="tab-callstack">
        <span slot="start" class="codicon codicon-call-stack"></span>
        Call Stack
      </vscode-panel-tab>
      <vscode-panel-tab id="tab-breakpoints">
        <span slot="start" class="codicon codicon-debug-breakpoint"></span>
        Breakpoints
      </vscode-panel-tab>
      <vscode-panel-tab id="tab-console">
        <span slot="start" class="codicon codicon-terminal"></span>
        Console
      </vscode-panel-tab>
      
      <vscode-panel-view id="view-variables">
        <vscode-tree-view>
          <vscode-tree-item label="Local" expanded>
            <vscode-tree-item label="self" expanded>
              <vscode-tree-item label="type: DapperDebugger"></vscode-tree-item>
              <vscode-tree-item label="breakpoints: []"></vscode-tree-item>
            </vscode-tree-item>
          </vscode-tree-item>
        </vscode-tree-view>
      </vscode-panel-view>
      
      <vscode-panel-view id="view-callstack">
        <vscode-tree-view>
          <vscode-tree-item label="Thread 1 (main)" expanded>
            <vscode-tree-item label="main.py:10"></vscode-tree-item>
            <vscode-tree-item label="main.py:5"></vscode-tree-item>
          </vscode-tree-item>
        </vscode-tree-view>
      </vscode-panel-view>
      
      <vscode-panel-view id="view-breakpoints">
        <vscode-listbox>
          <vscode-option>main.py:10</vscode-option>
          <vscode-option>utils.py:15</vscode-option>
        </vscode-listbox>
      </vscode-panel-view>
      
      <vscode-panel-view id="view-console" class="console-view">
        <div class="console-output">
          <div class="console-line">>>> Starting debug session...</div>
          <div class="console-line">>>> Breakpoint hit at main.py:10</div>
        </div>
        <div class="console-input">
          <vscode-text-field 
            placeholder="Type Python code here..." 
            class="console-textfield"
          >
            <span slot="start" class="codicon codicon-terminal"></span>
          </vscode-text-field>
        </div>
      </vscode-panel-view>
    </vscode-panels>

    <div class="status-bar">
      <vscode-badge>Python 3.9.0</vscode-badge>
      <vscode-badge appearance="secondary">Dapper v0.1.0</vscode-badge>
      <div style="flex: 1"></div>
      <span id="status-text">Ready</span>
    </div>

    <script nonce="${nonce}">
      // Handle button clicks
      document.getElementById('start-debugging').addEventListener('click', () => {
        vscode.postMessage({
          command: 'startDebugging'
        });
      });

      // Handle breakpoint toggling
      document.querySelectorAll('vscode-tree-item').forEach(item => {
        item.addEventListener('click', (e) => {
          const line = item.getAttribute('data-line');
          const file = item.getAttribute('data-file');
          if (line && file) {
            vscode.postMessage({
              command: 'setBreakpoint',
              file,
              line: parseInt(line)
            });
          }
        });
      });

      // Handle console input
      const consoleInput = document.querySelector('.console-textfield');
      consoleInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const command = consoleInput.value.trim();
          if (command) {
            vscode.postMessage({
              command: 'executeInConsole',
              code: command
            });
            consoleInput.value = '';
          }
        }
      });

      // Handle messages from the extension
      window.addEventListener('message', event => {
        const message = event.data;
        switch (message.command) {
          case 'updateStatus':
            document.getElementById('status-text').textContent = message.text;
            break;
          case 'updateVariables':
            // Update variables view
            break;
          case 'updateCallStack':
            // Update call stack
            break;
        }
      });
    </script>
  </body>
  </html>`;
}

function getNonce() {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
