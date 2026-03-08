import React from 'react';
import { DebugConfiguration } from '../../types/debug.js';
import {
  CheckboxField,
  EditableKeyValueListField,
  EditableStringListField,
  type KeyValueListItem,
  NumberInputField,
  RadioGroupField,
  SectionTitle,
  SingleSelectField,
  TextInputField,
  WarningBanner,
  type StringListItem,
} from './ConfigViewComponents.js';

interface SharedStepProps {
  config?: Partial<DebugConfiguration>;
  updateField: <K extends keyof DebugConfiguration>(field: K, value: DebugConfiguration[K]) => void;
}

interface BasicsStepProps extends SharedStepProps {}

const hasConflictingLaunchTarget = (config?: Partial<DebugConfiguration>) => (
  config?.request !== 'attach' && Boolean(config?.program && config?.module)
);

const hasConflictingAttachTarget = (config?: Partial<DebugConfiguration>) => (
  config?.request === 'attach' && Boolean(config?.processId && config?.host && config?.port)
);

export const BasicsStep: React.FC<BasicsStepProps> = ({ config, updateField }) => (
  <>
    <SectionTitle>Identity</SectionTitle>

    <TextInputField
      label="Configuration Name "
      value={config?.name || ''}
      onValueChange={(value: string) => updateField('name', value)}
      required
      hint="Appears in the debug dropdown in the Run panel."
      placeholder="My Python App"
    />

    <RadioGroupField
      label="Request"
      onValueChange={(value: string) => updateField('request', value as DebugConfiguration['request'])}
      hint={
        config?.request === 'attach'
          ? 'Attach either by PID or by connecting to an existing debug adapter host/port.'
          : 'Start a new Python process and attach the debugger immediately.'
      }
    >
      <vscode-radio
        label="launch"
        name="request"
        value="launch"
        checked={!config?.request || config.request === 'launch'}
      />
      <vscode-radio
        label="attach"
        name="request"
        value="attach"
        checked={config?.request === 'attach'}
      />
    </RadioGroupField>

    <SectionTitle>Target</SectionTitle>

    {hasConflictingLaunchTarget(config) && (
      <WarningBanner style={{ marginBottom: '10px' }}>
        ⚠ Both <strong>Program</strong> and <strong>Module</strong> are set.
        Choose exactly one launch target before saving or starting the session.
      </WarningBanner>
    )}

    {hasConflictingAttachTarget(config) && (
      <WarningBanner style={{ marginBottom: '10px' }}>
        ⚠ Both <strong>processId</strong> and <strong>host/port</strong> are set.
        Choose exactly one attach target before saving or starting the session.
      </WarningBanner>
    )}

    {config?.request !== 'attach' && (
      <TextInputField
        label="Program path"
        value={config?.program || ''}
        onValueChange={(value: string) => updateField('program', value)}
        hint={
          <>
            Run a specific file. Absolute path or VS Code variable — e.g. <code>{'${file}'}</code> for the currently open file.
            Leave <strong>Module</strong> blank when launching a file directly.
          </>
        }
        placeholder="${file}"
      />
    )}

    {config?.request !== 'attach' && (
      <TextInputField
        label="Module name"
        value={config?.module || ''}
        onValueChange={(value: string) => updateField('module', value)}
        hint={
          <>
            Run as a module: equivalent to <code>python -m package.module</code>.
            Leave <strong>Program path</strong> blank when launching a module.
          </>
        }
        placeholder="package.module"
      />
    )}

    {config?.request === 'attach' && (
      <>
        <TextInputField
          label="Process ID"
          value={config?.processId == null ? '' : String(config.processId)}
          onValueChange={(value: string) => updateField('processId', value)}
          hint="Attach to a local process by PID. Leave host/port empty when using this mode."
          placeholder="${command:pickProcess}"
        />

        <TextInputField
          label="Host"
          value={config?.host || ''}
          onValueChange={(value: string) => updateField('host', value)}
          hint="Host name of an already-running DAP endpoint. Leave Process ID empty when using host/port."
          placeholder="localhost"
        />

        <NumberInputField
          label="Port"
          value={config?.port}
          onValueChange={(value: number | undefined) => updateField('port', value)}
          hint="TCP port of the remote debug adapter. Requires Host when using host/port attach."
          placeholder="5678"
        />
      </>
    )}
  </>
);

interface RuntimeStepProps extends SharedStepProps {
  argsList: StringListItem[];
  envList: KeyValueListItem[];
  modulePathsList: StringListItem[];
  updateArgs: (newList: StringListItem[]) => void;
  updateEnv: (newList: KeyValueListItem[]) => void;
  updateModulePaths: (newList: StringListItem[]) => void;
  createStringListItem: (value?: string) => StringListItem;
  createKeyValueListItem: (key?: string, value?: string) => KeyValueListItem;
}

export const RuntimeStep: React.FC<RuntimeStepProps> = ({
  config,
  updateField,
  argsList,
  envList,
  modulePathsList,
  updateArgs,
  updateEnv,
  updateModulePaths,
  createStringListItem,
  createKeyValueListItem,
}) => (
  <>
    <SectionTitle>Paths</SectionTitle>

    <TextInputField
      label="Working directory"
      value={config?.cwd || ''}
      onValueChange={(value: string) => updateField('cwd', value)}
      hint="Current directory when the process starts. Defaults to workspace root."
      placeholder="${workspaceFolder}"
    />

    <TextInputField
      label="Virtual environment path"
      value={config?.venvPath || ''}
      onValueChange={(value: string) => updateField('venvPath', value)}
      hint="Relative or absolute path to a venv. Leave blank to use the workspace interpreter."
      placeholder=".venv"
    />

    <SectionTitle>Arguments</SectionTitle>

    <EditableStringListField
      items={argsList}
      emptyText="No arguments — click Add to append one."
      addLabel="+ Add argument"
      placeholder={(index: number) => `arg ${index + 1}`}
      hint={<>Passed to the program as <code>sys.argv[1:]</code>.</>}
      onChange={updateArgs}
      createItem={() => createStringListItem()}
    />

    {config?.request !== 'attach' && !!config?.module && (
      <>
        <SectionTitle>Module search paths</SectionTitle>
        <EditableStringListField
          items={modulePathsList}
          emptyText="No extra paths — click Add to append one."
          addLabel="+ Add search path"
          placeholder={() => '/path/to/dir'}
          hint={<>Extra directories prepended to <code>sys.path</code> when resolving the module.</>}
          onChange={updateModulePaths}
          createItem={() => createStringListItem()}
        />
      </>
    )}

    <SectionTitle>Environment variables</SectionTitle>

    <EditableKeyValueListField
      items={envList}
      emptyText="No environment overrides — click Add to define one."
      addLabel="+ Add variable"
      keyPlaceholder="NAME"
      valuePlaceholder="value"
      hint="Merged with the inherited environment of the VS Code process."
      onChange={updateEnv}
      createItem={() => createKeyValueListItem()}
    />
  </>
);

interface DebugStepProps extends SharedStepProps {}

export const DebugStep: React.FC<DebugStepProps> = ({ config, updateField }) => (
  <>
    <SectionTitle>Transport</SectionTitle>

    <SingleSelectField
      label="IPC transport"
      value={config?.ipcTransport || 'pipe'}
      onValueChange={(value: string) => updateField('ipcTransport', value as DebugConfiguration['ipcTransport'])}
      style={{ width: '200px' }}
      hint={
        <>
          Communication channel between VS Code and the debug adapter.
          <strong> pipe</strong> and <strong>unix</strong> use a local socket;
          <strong> tcp</strong> requires a port number below.
        </>
      }
    >
      <vscode-option description="Recommended" value="pipe">pipe</vscode-option>
      <vscode-option value="tcp">tcp</vscode-option>
      <vscode-option value="unix">unix socket</vscode-option>
    </SingleSelectField>

    {config?.ipcTransport === 'tcp' && (
      <NumberInputField
        label="Debug server port"
        value={config?.debugServer ?? 4711}
        onValueChange={(value: number | undefined) => updateField('debugServer', value ?? 4711)}
        hint="Port the debug adapter listens on when using TCP transport (default 4711)."
        emptyValue={4711}
      />
    )}

    <SectionTitle>Execution behaviour</SectionTitle>

    <div className="checkbox-group">
      <CheckboxField
        checked={Boolean(config?.frameEval)}
        label="Enable frame evaluation"
        hint="Dapper's low-overhead frame evaluator — improves performance during heavy stepping."
        onChange={(checked: boolean) => updateField('frameEval', checked)}
      />
      <CheckboxField
        checked={Boolean(config?.stopOnEntry)}
        label="Stop on entry"
        hint="Break on the very first statement before any user code runs."
        onChange={(checked: boolean) => updateField('stopOnEntry', checked)}
      />
      <CheckboxField
        checked={Boolean(config?.justMyCode)}
        label="Just My Code"
        hint="Skip stepping into standard library and third-party packages."
        onChange={(checked: boolean) => updateField('justMyCode', checked)}
      />
    </div>

    <SectionTitle>Subprocess debugging</SectionTitle>

    <div className="checkbox-group">
      <CheckboxField
        checked={Boolean(config?.subprocessAutoAttach)}
        label="Auto-attach to subprocesses"
        hint="Automatically attach the debugger to any child processes spawned at runtime."
        onChange={(checked: boolean) => updateField('subprocessAutoAttach', checked)}
      />
    </div>
  </>
);

interface ReviewStepProps {
  config?: Partial<DebugConfiguration>;
}

export const ReviewStep: React.FC<ReviewStepProps> = ({ config }) => {
  const finalConfig = {
    ...config,
    type: 'dapper',
    request: config?.request || 'launch',
  };

  return (
    <vscode-form-group>
      <pre className="review-json">
        {JSON.stringify(finalConfig, null, 2)}
      </pre>
    </vscode-form-group>
  );
};