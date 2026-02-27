import * as vscode from 'vscode';
import { BaseView } from '../BaseView.js';
import type { WebviewToHostMessage } from '../../debugViewProtocol.js';
import { DebugViewSessionWatcher } from '../../DebugViewSessionWatcher.js';

export class DebugView extends BaseView {
  private _selectedFrameId: number | null = null;
  private _selectedThreadId: number | null = null;
  private _watcher: DebugViewSessionWatcher | null = null;

  render(): string {
    const elementsUri = this.getWebviewUri('node_modules', '@vscode-elements', 'elements', 'dist', 'bundled.js');
    const cspSource = this.panel.webview.cspSource;
    const nonce = String(Date.now());

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src ${cspSource} https: data:; font-src ${cspSource};">
  <title>Debug View</title>
  <script type="module" nonce="${nonce}" src="${elementsUri}"></script>
</head>
<body style="display:flex;flex-direction:column;height:100vh;padding:0;margin:0;overflow:hidden">

  <!-- 1. Thread selector row (top) -->
  <div id="thread-row" style="display:flex;align-items:center;gap:8px;padding:4px 8px;flex-shrink:0">
    <vscode-icon name="run-all" aria-hidden="true"></vscode-icon>
    <vscode-single-select id="thread-select">
      <vscode-option value="">No active session</vscode-option>
    </vscode-single-select>
    <vscode-badge id="thread-state-badge">stopped</vscode-badge>
  </div>

  <!-- 2. Toolbar row -->
  <vscode-toolbar-container style="flex-shrink:0">
    <vscode-toolbar-button id="btn-continue" title="Continue (F5)">
      <vscode-icon name="debug-continue"></vscode-icon>
    </vscode-toolbar-button>
    <vscode-toolbar-button id="btn-pause" title="Pause (F6)">
      <vscode-icon name="debug-pause"></vscode-icon>
    </vscode-toolbar-button>
    <vscode-divider role="separator" style="height:20px"></vscode-divider>
    <vscode-toolbar-button id="btn-step-over" title="Step Over (F10)">
      <vscode-icon name="debug-step-over"></vscode-icon>
    </vscode-toolbar-button>
    <vscode-toolbar-button id="btn-step-into" title="Step Into (F11)">
      <vscode-icon name="debug-step-into"></vscode-icon>
    </vscode-toolbar-button>
    <vscode-toolbar-button id="btn-step-out" title="Step Out (Shift+F11)">
      <vscode-icon name="debug-step-out"></vscode-icon>
    </vscode-toolbar-button>
  </vscode-toolbar-container>
  <vscode-divider></vscode-divider>

  <!-- 3. Main split area (takes remaining height) -->
  <vscode-split-layout id="main-split" style="flex:1;min-height:0" initial-handle-position="35">

    <!-- Left pane: stack tree -->
    <div slot="start" style="display:flex;flex-direction:column;height:100%;overflow:hidden">
      <div style="padding:4px 8px;flex-shrink:0">
        <vscode-textfield id="stack-filter" placeholder="Filter frames..." style="width:100%"></vscode-textfield>
      </div>
      <vscode-scrollable style="flex:1;min-height:0">
        <vscode-tree id="stack-tree"></vscode-tree>
      </vscode-scrollable>
    </div>

    <!-- Right pane: source preview + variables -->
    <div slot="end" style="display:flex;flex-direction:column;height:100%;overflow:hidden">
      <vscode-scrollable id="source-scroll" style="flex:1;min-height:0">
        <pre id="source-lines" style="margin:0;padding:8px;font-family:var(--vscode-editor-font-family);font-size:var(--vscode-editor-font-size);white-space:pre-wrap"></pre>
        <div id="source-loading" style="display:none;padding:8px">
          <vscode-progress-ring></vscode-progress-ring>
        </div>
      </vscode-scrollable>
      <vscode-divider></vscode-divider>
      <vscode-collapsible title="Variables" open style="flex-shrink:0;max-height:40%;overflow:auto">
        <vscode-table id="vars-table" bordered-columns resizable-columns style="width:100%">
          <vscode-table-header slot="header">
            <vscode-table-header-cell>Name</vscode-table-header-cell>
            <vscode-table-header-cell>Value</vscode-table-header-cell>
            <vscode-table-header-cell>Type</vscode-table-header-cell>
          </vscode-table-header>
          <vscode-table-body id="vars-body" slot="body"></vscode-table-body>
        </vscode-table>
      </vscode-collapsible>
    </div>

  </vscode-split-layout>

  <script type="module" nonce="${nonce}">
    const vscodeApi = acquireVsCodeApi();

    // Toolbar buttons
    document.getElementById('btn-continue').addEventListener('click', () => {
      vscodeApi.postMessage({ command: 'continue' });
    });
    document.getElementById('btn-pause').addEventListener('click', () => {
      vscodeApi.postMessage({ command: 'pause' });
    });
    document.getElementById('btn-step-over').addEventListener('click', () => {
      vscodeApi.postMessage({ command: 'stepOver' });
    });
    document.getElementById('btn-step-into').addEventListener('click', () => {
      vscodeApi.postMessage({ command: 'stepInto' });
    });
    document.getElementById('btn-step-out').addEventListener('click', () => {
      vscodeApi.postMessage({ command: 'stepOut' });
    });

    // Button state management
    function updateButtonState(state) {
      const btnContinue = document.getElementById('btn-continue');
      const btnPause = document.getElementById('btn-pause');
      const btnStepOver = document.getElementById('btn-step-over');
      const btnStepInto = document.getElementById('btn-step-into');
      const btnStepOut = document.getElementById('btn-step-out');

      if (state === 'running') {
        btnStepOver.setAttribute('disabled', '');
        btnStepInto.setAttribute('disabled', '');
        btnStepOut.setAttribute('disabled', '');
        btnContinue.setAttribute('disabled', '');
        btnPause.removeAttribute('disabled');
      } else if (state === 'paused') {
        btnStepOver.removeAttribute('disabled');
        btnStepInto.removeAttribute('disabled');
        btnStepOut.removeAttribute('disabled');
        btnContinue.removeAttribute('disabled');
        btnPause.setAttribute('disabled', '');
      } else if (state === 'stopped') {
        btnContinue.setAttribute('disabled', '');
        btnPause.setAttribute('disabled', '');
        btnStepOver.setAttribute('disabled', '');
        btnStepInto.setAttribute('disabled', '');
        btnStepOut.setAttribute('disabled', '');
      }
    }

    // Thread select
    document.getElementById('thread-select').addEventListener('vsc-change', (e) => {
      vscodeApi.postMessage({ command: 'selectThread', threadId: Number(e.detail.value) });
    });

    // Stack filter
    let allFrames = [];
    let selectedFrameId = null;

    document.getElementById('stack-filter').addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = allFrames.filter(frame =>
        frame.name.toLowerCase().includes(query) || frame.source.toLowerCase().includes(query)
      );
      renderStack(filtered);
      vscodeApi.postMessage({ command: 'filterStack', query: e.target.value });
    });

    // Stack tree selection
    document.getElementById('stack-tree').addEventListener('vsc-select', (e) => {
      const frameId = Number(e.detail.value);
      selectedFrameId = frameId;
      vscodeApi.postMessage({ command: 'selectFrame', frameId });
      vscodeApi.postMessage({ command: 'expandFrame', frameId });
    });

    // Build decorations for a frame
    function buildDecorations(frame) {
      const decorations = [];
      decorations.push({ appearance: 'counter-badge', content: String(frame.line) });
      if (frame.isOptimized) {
        decorations.push({ appearance: 'counter-badge', content: 'OPT' });
      }
      if (frame.isSynthetic) {
        decorations.push({ appearance: 'counter-badge', content: 'SYN' });
      }
      if (frame.isCython) {
        decorations.push({ appearance: 'counter-badge', content: 'CY' });
      }
      return decorations;
    }

    // Render stack tree
    function renderStack(frames) {
      const stackTree = document.getElementById('stack-tree');
      stackTree.data = frames.map(frame => ({
        label: frame.name,
        description: \`\${frame.source}:\${frame.line}\`,
        value: String(frame.id),
        icons: {
          leaf: frame.id === selectedFrameId ? 'debug-stackframe-focused' : 'debug-stackframe'
        },
        decorations: buildDecorations(frame)
      }));
    }

    // Render source lines
    function renderSourceLines(lines) {
      const sourceLinesEl = document.getElementById('source-lines');
      const sourceLoading = document.getElementById('source-loading');
      sourceLinesEl.innerHTML = '';
      lines.forEach((line, index) => {
        const span = document.createElement('span');
        span.textContent = line;
        if (index === 2) {
          span.style.cssText = 'background:var(--vscode-editor-lineHighlightBackground);display:block';
        } else {
          span.style.cssText = 'display:block';
        }
        sourceLinesEl.appendChild(span);
      });
      sourceLoading.style.display = 'none';
    }

    // Render variables
    function renderVariables(variables) {
      const varsBody = document.getElementById('vars-body');
      varsBody.innerHTML = '';
      variables.forEach(variable => {
        const row = document.createElement('vscode-table-row');

        const nameCell = document.createElement('vscode-table-cell');
        if (variable.hasChildren) {
          const icon = document.createElement('vscode-icon');
          icon.setAttribute('name', 'chevron-right');
          icon.style.cursor = 'pointer';
          icon.addEventListener('click', () => {
            vscodeApi.postMessage({ command: 'expandFrame', frameId: variable.variablesReference });
          });
          nameCell.appendChild(icon);
        }
        nameCell.appendChild(document.createTextNode(variable.name));

        const valueCell = document.createElement('vscode-table-cell');
        valueCell.textContent = variable.value;

        const typeCell = document.createElement('vscode-table-cell');
        typeCell.textContent = variable.type ?? '';

        row.appendChild(nameCell);
        row.appendChild(valueCell);
        row.appendChild(typeCell);
        varsBody.appendChild(row);
      });
    }

    // Handle host→webview messages
    window.addEventListener('message', (event) => {
      const message = event.data;
      switch (message.command) {
        case 'stackTrace': {
          allFrames = message.frames;
          renderStack(message.frames);
          break;
        }
        case 'variables': {
          renderVariables(message.variables);
          break;
        }
        case 'sourceLines': {
          renderSourceLines(message.lines);
          break;
        }
        case 'threads': {
          const threadSelect = document.getElementById('thread-select');
          while (threadSelect.firstChild) {
            threadSelect.removeChild(threadSelect.firstChild);
          }
          message.threads.forEach(t => {
            const option = document.createElement('vscode-option');
            option.setAttribute('value', String(t.id));
            option.textContent = \`\${t.name} (\${t.state})\`;
            threadSelect.appendChild(option);
          });
          const badge = document.getElementById('thread-state-badge');
          if (message.threads.length > 0) {
            badge.textContent = message.threads[0].state;
          }
          break;
        }
        case 'sessionState': {
          updateButtonState(message.state);
          document.getElementById('thread-state-badge').textContent = message.state;
          break;
        }
        case 'clearStack': {
          const stackTree = document.getElementById('stack-tree');
          stackTree.data = [];
          document.getElementById('source-lines').innerHTML = '';
          document.getElementById('vars-body').innerHTML = '';
          allFrames = [];
          break;
        }
      }
    });
  </script>
</body>
</html>`;
  }

  setupMessageHandlers(panel: vscode.WebviewPanel): void {
    panel.webview.onDidReceiveMessage(
      (message: WebviewToHostMessage) => this._handleMessage(message),
      null,
      this.disposables
    );
    this._watcher = new DebugViewSessionWatcher(panel);
    this.disposables.push(this._watcher);
  }

  private _handleMessage(message: WebviewToHostMessage): void {
    switch (message.command) {
      case 'continue':
        vscode.commands.executeCommand('workbench.action.debug.continue');
        break;
      case 'pause':
        vscode.commands.executeCommand('workbench.action.debug.pause');
        break;
      case 'stepOver':
        vscode.commands.executeCommand('workbench.action.debug.stepOver');
        break;
      case 'stepInto':
        vscode.commands.executeCommand('workbench.action.debug.stepInto');
        break;
      case 'stepOut':
        vscode.commands.executeCommand('workbench.action.debug.stepOut');
        break;
      case 'selectFrame':
        this._selectedFrameId = message.frameId;
        this._watcher?.handleFetchVariables(message.frameId);
        break;
      case 'expandFrame':
        this._watcher?.handleFetchVariables(message.frameId);
        break;
      case 'filterStack':
        // No-op on host side — filtering is client-side only
        break;
      case 'selectThread':
        this._selectedThreadId = message.threadId;
        this._watcher?.handleSelectThread(message.threadId);
        break;
    }
  }
}
