# VS Code Extension Development

The VS Code extension source code is located in `vscode/extension`. It is a separate npm project that must be built before running the Python unit tests that depend on it.

## Setup

1. **Navigate to the extension directory:**
   ```bash
   cd vscode/extension
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Build the extension:**
   ```bash
   npm run build
   ```

   For development with auto-rebuild on changes:
   ```bash
   npm run watch
   ```

## Running the Extension

1. Open the `vscode/extension` folder in VS Code.
2. Press `F5` to launch the Extension Development Host.

The Extension Development Host opens a new VS Code window with the extension loaded. You can set breakpoints in the extension TypeScript source and debug it like any other Node.js project.

## See Also

- [Setup](setup.md)
