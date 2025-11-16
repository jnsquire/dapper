# VS Code Extension Plan for Dapper Debug Adapter

## Overview

This document outlines the plan for creating a VS Code extension that provides enhanced support for the dapper debug adapter with Python. The extension will feature React-based webviews with server-side rendering (SSR) for optimal performance and user experience.

## Project Structure

```
vscode/extension/
├── package.json                 # Extension manifest
├── tsconfig.json               # TypeScript configuration
├── webpack.config.js           # Build configuration
├── src/
│   ├── extension.ts           # Main extension entry point
│   ├── debugAdapter/
│   │   ├── dapperDebugAdapter.ts  # Debug adapter provider
│   │   └── configurationSchema.ts # Launch/attach configurations
│   ├── webview/
│   │   ├── reactSSRProvider.ts    # React SSR webview provider
│   │   ├── ssrRenderer.ts         # Server-side rendering logic
│   │   └── webviewCommunication.ts # Message handling
│   ├── ui/
│   │   ├── components/            # React components
│   │   │   ├── VariableInspector.tsx
│   │   │   ├── CallStackView.tsx
│   │   │   └── BreakpointsPanel.tsx
│   │   └── styles/                # CSS/styling
│   └── commands/
│       └── debugCommands.ts       # Extension commands
├── resources/
│   └── icons/                     # Extension icons
├── test/
│   └── suite/                     # Test files
└── README.md
```

## Key Features

### 1. Debug Adapter Integration
- **Custom Debug Adapter Provider**: Register dapper as a debug adapter type
- **Configuration Schema**: Provide IntelliSense for dapper launch configurations
- **IPC Support**: Handle named pipes, Unix sockets, and TCP connections
- **Frame Evaluation**: Support for high-performance frame evaluation mode

### 2. React SSR Webview System
- **Server-Side Rendering**: Use React's renderToString for initial HTML generation
- **Hydration**: Client-side hydration for interactive components
- **Performance**: Faster initial load and better SEO-like benefits
- **State Management**: Efficient state synchronization between extension and webview

### 3. Enhanced Debugging UI
- **Variable Inspector**: Rich variable display with expandable objects
- **Call Stack View**: Interactive call stack navigation
- **Breakpoints Panel**: Visual breakpoint management
- **Debug Console**: Enhanced console with syntax highlighting

### 4. Extension Commands
- `dapper.startDebugging`: Start debugging with dapper
- `dapper.toggleBreakpoint`: Toggle breakpoints
- `dapper.showVariableInspector`: Open variable inspector webview
- `dapper.configureSettings`: Open extension settings

## Technical Implementation

### React SSR Architecture
```typescript
// Server-side rendering in extension context
const renderWebviewHTML = (component: React.ComponentType, props: any) => {
  const html = renderToString(React.createElement(component, props));
  return `
    <!DOCTYPE html>
    <html>
      <head>
        <style>${styles}</style>
      </head>
      <body>
        <div id="root">${html}</div>
        <script>
          window.initialProps = ${JSON.stringify(props)};
        </script>
        <script src="${webviewScriptPath}"></script>
      </body>
    </html>
  `;
};
```

### Debug Adapter Configuration
```json
{
  "type": "dapper",
  "request": "launch",
  "name": "Python: Dapper Debug",
  "program": "${file}",
  "debugServer": 4711,
  "useIpc": true,
  "frameEval": true,
  "inProcess": false
}
```

### Webview Communication Protocol
- **Extension → Webview**: Debug events, variable updates, stack changes
- **Webview → Extension**: User interactions, breakpoint toggles, variable expansion requests

## Development Workflow

### Phase 1: Foundation Setup
1. Create extension directory structure
2. Configure TypeScript and webpack build system
3. Set up package.json with VS Code extension metadata
4. Initialize testing framework

### Phase 2: Core Debug Adapter Integration
1. Implement debug adapter provider
2. Create configuration schemas for launch/attach
3. Register extension with VS Code debug API
4. Test basic debug session initiation

### Phase 3: React SSR Webview System
1. Set up React SSR infrastructure
2. Implement webview provider and communication
3. Create base webview HTML template system
4. Test server-side rendering with simple components

### Phase 4: Debug UI Components
1. Develop VariableInspector component
2. Create CallStackView component
3. Implement BreakpointsPanel component
4. Add styling and responsive design

### Phase 5: Integration and Polish
1. Integrate all components with debug adapter
2. Implement extension commands
3. Add error handling and validation
4. Performance optimization

### Phase 6: Testing and Documentation
# Prioritized Development Checklist

## 🚀 High Priority (MVP)
- [ ] Complete ConfigView component
  - [ ] Fix event handling for form inputs
  - [ ] Implement form validation
  - [ ] Add save/load configuration functionality
- [ ] Implement Call Stack visualization
  - [ ] Display call hierarchy
  - [ ] Add navigation between stack frames
- [ ] Basic Testing Infrastructure
  - [ ] Unit tests for core components
  - [ ] Integration tests for debug adapter
  - [ ] Webview component tests

## 📈 Medium Priority (Post-MVP)
- [ ] Debug Console Integration
  - [ ] REPL for expression evaluation
  - [ ] Command history
  - [ ] Syntax highlighting
- [ ] Enhanced Breakpoint Management
  - [ ] Conditional breakpoints
  - [ ] Function breakpoints
  - [ ] Hit count breakpoints
- [ ] Variable Inspection
  - [ ] Expandable object inspection
  - [ ] Variable value modification
  - [ ] Watch expressions

## 🔧 Low Priority (Future Enhancements)
- [ ] Performance Profiling
  - [ ] Execution time measurement
  - [ ] Memory usage visualization
- [ ] Advanced Debugging Features
  - [ ] Remote debugging
  - [ ] Multi-thread debugging
  - [ ] Just-in-time debugging
- [ ] Extension Ecosystem
  - [ ] API for other extensions
  - [ ] Custom debugger themes
  - [ ] Plugin system for language support

## 📚 Documentation & Polish
- [ ] User Documentation
  - [ ] Getting started guide
  - [ ] Feature documentation
  - [ ] Troubleshooting guide
- [ ] Developer Documentation
  - [ ] Architecture overview
  - [ ] Contribution guidelines
  - [ ] API reference

## 🚢 Release Preparation
- [ ] CI/CD Pipeline
  - [ ] Automated testing
  - [ ] Build automation
  - [ ] Release process
- [ ] Marketplace Assets
  - [ ] Extension icon
  - [ ] Screenshots
  - [ ] Demo gifs
  - [ ] Extension description

## 🏗️ Technical Debt & Refactoring
- [ ] Code Quality
  - [ ] TypeScript strict mode
  - [ ] Performance optimization
  - [ ] Accessibility improvements
- [ ] Testing Coverage
  - [ ] Increase test coverage
  - [ ] Add E2E tests
  - [ ] Performance benchmarks

## Dependencies

### Extension Dependencies
- `@types/vscode`: VS Code API types
- `@types/react`: React types
- `react`: React library for SSR
- `react-dom`: React DOM renderer
- `webpack`: Module bundler
- `typescript`: TypeScript compiler

### Development Dependencies
- `@vscode/test-electron`: VS Code testing utilities
- `eslint`: Code linting
- `prettier`: Code formatting
- `vitest`: Fast, modern unit test runner

## 💡 Testing
- `npm run test` → `vitest run` (used in CI/VSIX workflows)
- `npm run test:watch` → `vitest` watch mode for iterating on extensions
- `vitest.config.ts` aliases `vscode` to `test/__mocks__/vscode.mjs` and sets `environment: 'node'` + `globals: true`

## Configuration Schema

The extension will provide comprehensive configuration support for all dapper features:

```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "default": "Python: Dapper" },
    "type": { "type": "string", "enum": ["dapper"] },
    "request": { "type": "string", "enum": ["launch", "attach"] },
    "program": { "type": "string" },
    "args": { "type": "array", "items": { "type": "string" } },
    "cwd": { "type": "string" },
    "debugServer": { "type": "number" },
    "useIpc": { "type": "boolean" },
    "ipcTransport": { "type": "string", "enum": ["tcp", "unix", "pipe"] },
    "frameEval": { "type": "boolean" },
    "inProcess": { "type": "boolean" },
    "stopOnEntry": { "type": "boolean" },
    "justMyCode": { "type": "boolean" }
  }
}
```

## Webview Message Protocol

### Extension to Webview Messages
```typescript
interface DebugEventMessage {
  type: 'debugEvent';
  event: 'stopped' | 'continued' | 'exited' | 'terminated';
  data: any;
}

interface VariableUpdateMessage {
  type: 'variableUpdate';
  variables: Variable[];
}

interface StackUpdateMessage {
  type: 'stackUpdate';
  stackFrames: StackFrame[];
}
```

### Webview to Extension Messages
```typescript
interface VariableExpandRequest {
  type: 'expandVariable';
  variableReference: number;
}

interface BreakpointToggleRequest {
  type: 'toggleBreakpoint';
  source: Source;
  line: number;
}

interface StackFrameSelectRequest {
  type: 'selectStackFrame';
  frameId: number;
}
```

## Performance Considerations

### SSR Benefits
- **Faster Initial Load**: Pre-rendered HTML reduces time-to-first-content
- **Better UX**: No layout shift during component initialization
- **SEO-like Benefits**: Improved accessibility and searchability within VS Code

### Optimization Strategies
- **Component Memoization**: Use React.memo for expensive components
- **Virtual Scrolling**: For large variable lists and call stacks
- **Lazy Loading**: Load debug data on-demand
- **Message Batching**: Reduce communication overhead

## Testing Strategy

### Unit Tests
- Debug adapter provider functionality
- React component rendering and behavior
- Webview communication protocols
- Configuration validation

### Integration Tests
- End-to-end debug session workflows
- Webview interaction with debug adapter
- Extension command execution
- Error handling scenarios

### Manual Testing
- VS Code extension marketplace compatibility
- Cross-platform functionality (Windows, macOS, Linux)
- Performance under heavy debug sessions
- User experience validation

## Release Plan

### Version 1.0.0
- Basic debug adapter integration
- Core React SSR webview system
- Variable inspector and call stack view
- Essential extension commands

### Version 1.1.0
- Enhanced UI components
- Performance optimizations
- Additional configuration options
- Improved error handling

### Version 1.2.0
- Advanced debugging features
- Custom themes support
- Extension marketplace release
- Comprehensive documentation

## Conclusion

This plan provides a comprehensive roadmap for creating a modern VS Code extension that enhances the dapper debug adapter experience with React SSR webviews. The approach prioritizes performance, user experience, and maintainability while leveraging the full capabilities of both VS Code's extension API and React's component ecosystem.

The modular architecture allows for incremental development and testing, ensuring a robust and polished final product that integrates seamlessly with the existing dapper debug adapter infrastructure.
