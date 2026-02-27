import * as vscode from 'vscode';
import * as path from 'path';

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
    try {
      json = JSON.parse(content);
    } catch {
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
    await vscode.workspace.fs.writeFile(launchUri, Buffer.from(JSON.stringify(json, null, 2), 'utf8'));
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
