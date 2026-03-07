import * as vscode from 'vscode';
import * as path from 'path';

type JsonObject = Record<string, unknown>;

function stripJsonComments(content: string): string {
  let result = '';
  let inString = false;
  let isEscaped = false;
  let inLineComment = false;
  let inBlockComment = false;

  for (let index = 0; index < content.length; index += 1) {
    const current = content[index];
    const next = content[index + 1];

    if (inLineComment) {
      if (current === '\n') {
        inLineComment = false;
        result += current;
      }
      continue;
    }

    if (inBlockComment) {
      if (current === '*' && next === '/') {
        inBlockComment = false;
        index += 1;
      } else if (current === '\n') {
        result += current;
      }
      continue;
    }

    if (inString) {
      result += current;
      if (isEscaped) {
        isEscaped = false;
      } else if (current === '\\') {
        isEscaped = true;
      } else if (current === '"') {
        inString = false;
      }
      continue;
    }

    if (current === '/' && next === '/') {
      inLineComment = true;
      index += 1;
      continue;
    }

    if (current === '/' && next === '*') {
      inBlockComment = true;
      index += 1;
      continue;
    }

    if (current === '"') {
      inString = true;
    }

    result += current;
  }

  return result;
}

function parseJsoncObject(content: string): JsonObject | undefined {
  try {
    const parsed = JSON.parse(stripJsonComments(content));
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      return undefined;
    }
    return parsed as JsonObject;
  } catch {
    return undefined;
  }
}

/**
 * Inserts a debug configuration into the `.vscode/launch.json` for the given workspace folder.
 * If `launch.json` doesn't exist, it will be created. If multiple workspace folders exist, a prompt will be shown.
 */
export async function insertLaunchConfiguration(config: any, folder?: vscode.WorkspaceFolder): Promise<boolean> {
  // Choose workspace folder if necessary
  const folders = vscode.workspace.workspaceFolders;
  if (!folder) {
    if (!folders || folders.length === 0) {
      vscode.window.showErrorMessage('No workspace folder is open');
      return false;
    }
    if (folders.length === 1) folder = folders[0];
    else {
      const picked = await vscode.window.showQuickPick(folders.map(f => f.name), { placeHolder: 'Select workspace folder for launch.json' });
      if (!picked) return false;
      folder = folders.find(f => f.name === picked);
    }
  }

  if (!folder) {
    vscode.window.showErrorMessage('Workspace folder not selected');
    return false;
  }

  const folderPath = folder.uri.fsPath;
  const vscodeDir = path.join(folderPath, '.vscode');
  const launchPath = path.join(vscodeDir, 'launch.json');
  const launchUri = vscode.Uri.file(launchPath);
  const vscodeUri = vscode.Uri.file(vscodeDir);

  try {
    // Ensure .vscode directory exists
    await vscode.workspace.fs.createDirectory(vscodeUri);
  } catch (err) {
    // Non-fatal; directory creation may silently fail if it exists
  }

  // Read existing launch.json (if present). Any read failure is treated as
  // "file doesn't exist yet" — a failed write will surface the real error.
  let existingData: Uint8Array | undefined;
  try {
    existingData = await vscode.workspace.fs.readFile(launchUri);
  } catch {
    // File not found or unreadable — will create a fresh one below.
  }

  // Build the JSON to write
  let json: any;
  if (existingData) {
    const content = new TextDecoder('utf-8').decode(existingData);
    json = parseJsoncObject(content);

    if (!json) {
      const open = 'Open launch.json';
      const choice = await vscode.window.showWarningMessage(
        'Existing .vscode/launch.json is invalid JSON. Please fix the file before using this feature.',
        open,
      );
      if (choice === open) {
        const doc = await vscode.workspace.openTextDocument(launchUri);
        await vscode.window.showTextDocument(doc);
      }
      return false;
    }

    if (!json.configurations || !Array.isArray(json.configurations)) {
      json.configurations = [];
    }

    // Check for duplicates by name and program (best-effort)
    const isDuplicate = json.configurations.some(
      (c: any) => c.name === config.name && c.program === config.program,
    );
    if (isDuplicate) {
      const replace = 'Replace existing';
      const addAny = 'Add duplicate';
      const choice = await vscode.window.showInformationMessage(
        'A configuration with the same name and program exists in launch.json. Replace it or add a duplicate?',
        replace,
        addAny,
      );
      if (choice === replace) {
        json.configurations = json.configurations.map((c: any) =>
          c.name === config.name && c.program === config.program ? config : c,
        );
      } else if (choice === addAny) {
        json.configurations.push(config);
      } else {
        return false; // user cancelled
      }
    } else {
      json.configurations.push(config);
    }
  } else {
    json = { version: '0.2.0', configurations: [config] };
  }

  try {
    const serialized = JSON.stringify(json, null, 2);

    await vscode.workspace.fs.writeFile(launchUri, Buffer.from(serialized, 'utf8'));
    try {
      const doc = await vscode.workspace.openTextDocument(launchUri);
      await vscode.window.showTextDocument(doc);
    } catch {
      // Non-fatal: opening for review is best-effort.
    }
    return true;
  } catch (err) {
    vscode.window.showErrorMessage(`Failed to write launch.json: ${err}`);
    return false;
  }
}
