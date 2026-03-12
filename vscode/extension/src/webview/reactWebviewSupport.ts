import * as vscode from 'vscode';

export interface WebviewScriptAsset {
  path: string;
  module?: boolean;
}

export interface ReactWebviewDocumentOptions {
  webview: vscode.Webview;
  extensionUri: vscode.Uri;
  title: string;
  assetRoot?: readonly string[];
  bodyHtml?: string;
  stylesheets?: readonly string[];
  scripts?: readonly WebviewScriptAsset[];
  nonce?: string;
  additionalCspDirectives?: string;
}

const DEFAULT_ASSET_ROOT = ['out', 'compiled'] as const;

function splitPathSegments(path: string): string[] {
  return path.split('/').filter(Boolean);
}

function resolveSegments(assetRoot: readonly string[], assetPath?: string): string[] {
  const segments = [...assetRoot];
  if (assetPath) {
    segments.push(...splitPathSegments(assetPath));
  }
  return segments;
}

export function getWebviewResourceRoot(
  extensionUri: vscode.Uri,
  assetRoot: readonly string[] = DEFAULT_ASSET_ROOT,
): vscode.Uri {
  return vscode.Uri.joinPath(extensionUri, ...assetRoot);
}

export function getWebviewAssetUri(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  assetPath: string,
  assetRoot: readonly string[] = DEFAULT_ASSET_ROOT,
): vscode.Uri {
  return webview.asWebviewUri(
    vscode.Uri.joinPath(extensionUri, ...resolveSegments(assetRoot, assetPath)),
  );
}

export function renderReactWebviewDocument({
  webview,
  extensionUri,
  title,
  assetRoot = DEFAULT_ASSET_ROOT,
  bodyHtml = '<div id="root"></div>',
  stylesheets = [],
  scripts = [],
  nonce = String(Date.now()),
  additionalCspDirectives,
}: ReactWebviewDocumentOptions): string {
  const styleTags = stylesheets
    .map((stylesheet) => {
      const href = getWebviewAssetUri(webview, extensionUri, stylesheet, assetRoot);
      return `          <link rel="stylesheet" href="${href}" />`;
    })
    .join('\n');

  const scriptTags = scripts
    .map((script) => {
      const src = getWebviewAssetUri(webview, extensionUri, script.path, assetRoot);
      const typeAttribute = script.module ? ' type="module"' : '';
      return `          <script${typeAttribute} nonce="${nonce}" src="${src}"></script>`;
    })
    .join('\n');

  const cspParts = [
    `default-src 'none'`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}'`,
    `img-src ${webview.cspSource} https: data:`,
    `font-src ${webview.cspSource}`,
  ];
  if (additionalCspDirectives) {
    cspParts.push(additionalCspDirectives.trim());
  }

  return `
      <!doctype html>
      <html>
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <meta http-equiv="Content-Security-Policy" content="${cspParts.join('; ')};" />
          <title>${title}</title>
${styleTags}
${scriptTags}
        </head>
        <body>
          ${bodyHtml}
        </body>
      </html>`;
}