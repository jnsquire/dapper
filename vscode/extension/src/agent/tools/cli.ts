/**
 * dapper_cli - Phase 1 command-style wrapper over the existing Dapper LM tools.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { jsonResult, errorResult } from '../toolUtils.js';
import type { LaunchService } from '../../debugAdapter/launchService.js';
import { LaunchTool } from './launch.js';
import { ExecutionTool } from './execution.js';
import { EvaluateTool } from './evaluate.js';
import { StateTool } from './state.js';
import { BreakpointsTool } from './breakpoints.js';
import { InspectVariableTool } from './inspectVariable.js';

interface DapperCliInput {
  command: string;
  sessionId?: string;
  threadId?: number;
}

interface CliLocation {
  file: string;
  line: number;
  function?: string;
}

interface CliCommandResult {
  command: string;
  status: 'ok' | 'error';
  summary: string;
  result?: unknown;
  error?: string;
}

interface CliExecutionResult {
  sessionId?: string;
  threadId?: number;
  frameIndex: number;
  location?: CliLocation;
  command: CliCommandResult;
  text?: string;
}

interface SessionSelection {
  sessionId: string;
  session: vscode.DebugSession;
}

interface SessionState {
  threadId?: number;
  frameIndex: number;
  lastKnownLocation?: CliLocation;
}

interface SnapshotLike {
  threadId?: number;
  callStack?: Array<{ name?: string; file?: string; line?: number }>;
  location?: string;
  locals?: Record<string, string>;
  globals?: Record<string, string>;
}

interface InspectNodeLike {
  name?: string;
  value?: string;
  children?: InspectNodeLike[];
}

interface ToolArgumentHelp {
  name: string;
  required: boolean;
  description: string;
}

interface ToolHelpEntry {
  name: string;
  displayName: string;
  purpose: string;
  arguments: ToolArgumentHelp[];
}

interface ToolSchemaProperty {
  description?: string;
}

interface ToolManifestEntry {
  name: string;
  displayName?: string;
  modelDescription?: string;
  inputSchema?: {
    properties?: Record<string, ToolSchemaProperty | undefined>;
    required?: string[];
  };
}

interface ExtensionPackageManifest {
  contributes?: {
    languageModelTools?: unknown[];
  };
}

type JsonObject = Record<string, unknown>;

interface CliCommandSpecDefinition {
  verb: string;
  aliases: readonly string[];
  args: 'none' | string;
  description: string;
}

const CLI_COMMAND_SPECS = [
  {
    verb: 'help',
    aliases: ['h'],
    args: 'none',
    description: 'Show CLI help plus a summary of the underlying Dapper tools and their arguments.',
  },
  {
    verb: 'run',
    aliases: [],
    args: 'none',
    description: 'Launch the active Python file and wait for the first stop.',
  },
  {
    verb: 'continue',
    aliases: ['c'],
    args: 'none',
    description: 'Resume execution until the next stop.',
  },
  {
    verb: 'next',
    aliases: ['n'],
    args: 'none',
    description: 'Step over the next line in the selected thread.',
  },
  {
    verb: 'step',
    aliases: ['s'],
    args: 'none',
    description: 'Step into the next call in the selected thread.',
  },
  {
    verb: 'finish',
    aliases: [],
    args: 'none',
    description: 'Step out of the current frame.',
  },
  {
    verb: 'quit',
    aliases: ['q'],
    args: 'none',
    description: 'Terminate the selected Dapper session.',
  },
  {
    verb: 'break',
    aliases: ['b'],
    args: '<file>:<line>|<function>:<line>',
    description: 'Add a source breakpoint at the given file, Python filename stem, or current stack function name and line.',
  },
  {
    verb: 'clear',
    aliases: [],
    args: '[<file>[:<line>]]',
    description: 'Remove a breakpoint at the current line, a specific line, or clear a whole file.',
  },
  {
    verb: 'disable',
    aliases: [],
    args: '[<file>[:<line>]]',
    description: 'Disable a breakpoint at the current line, a specific line, or all breakpoints in a file.',
  },
  {
    verb: 'enable',
    aliases: [],
    args: '[<file>[:<line>]]',
    description: 'Enable a breakpoint at the current line, a specific line, or all breakpoints in a file.',
  },
  {
    verb: 'print',
    aliases: ['p'],
    args: '<expression>',
    description: 'Evaluate an expression in the selected frame.',
  },
  {
    verb: 'where',
    aliases: ['bt'],
    args: 'none',
    description: 'Show the current call stack.',
  },
  {
    verb: 'locals',
    aliases: [],
    args: 'none',
    description: 'Show locals for the selected frame.',
  },
  {
    verb: 'globals',
    aliases: [],
    args: 'none',
    description: 'Show globals for the selected frame.',
  },
  {
    verb: 'list',
    aliases: ['l'],
    args: '[<start>[,<end>]]',
    description: 'Show source lines around the selected frame or for an explicit range.',
  },
  {
    verb: 'up',
    aliases: [],
    args: 'none',
    description: 'Move to the caller frame.',
  },
  {
    verb: 'down',
    aliases: [],
    args: 'none',
    description: 'Move to the callee frame.',
  },
  {
    verb: 'frame',
    aliases: [],
    args: '<index>',
    description: 'Select a specific stack frame by zero-based index.',
  },
] as const satisfies readonly CliCommandSpecDefinition[];

type CliVerb = typeof CLI_COMMAND_SPECS[number]['verb'];

interface ParsedCommand {
  raw: string;
  verb: CliVerb;
  arg?: string;
}

const CLI_COMMAND_HELP = CLI_COMMAND_SPECS.map(spec => ({
  command: spec.verb,
  aliases: spec.aliases,
  args: spec.args,
  description: spec.description,
}));

const COMMAND_ALIASES: Record<string, CliVerb> = Object.fromEntries(
  CLI_COMMAND_SPECS.flatMap(spec => [
    [spec.verb, spec.verb],
    ...spec.aliases.map((alias) => [alias, spec.verb] as const),
  ]),
) as Record<string, CliVerb>;

export class DapperCliTool implements vscode.LanguageModelTool<DapperCliInput> {
  private readonly launchTool: LaunchTool;
  private readonly executionTool: ExecutionTool;
  private readonly evaluateTool: EvaluateTool;
  private readonly stateTool: StateTool;
  private readonly breakpointsTool: BreakpointsTool;
  private readonly inspectVariableTool: InspectVariableTool;
  private readonly underlyingToolHelp: ToolHelpEntry[];
  private readonly sessionState = new Map<string, SessionState>();

  constructor(
    private readonly registry: JournalRegistry,
    launchService: LaunchService,
    packageManifest: ExtensionPackageManifest,
  ) {
    this.launchTool = new LaunchTool(registry, launchService);
    this.executionTool = new ExecutionTool(registry);
    this.evaluateTool = new EvaluateTool(registry);
    this.stateTool = new StateTool(registry);
    this.breakpointsTool = new BreakpointsTool(registry);
    this.inspectVariableTool = new InspectVariableTool(registry);
    this.underlyingToolHelp = buildUnderlyingToolHelp(packageManifest);
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<DapperCliInput>,
    token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const commandSegments = this._splitCommands(options.input.command);
    const commandResults: CliCommandResult[] = [];
    let sessionId = options.input.sessionId;
    let threadId = options.input.threadId;
    let frameIndex = 0;
    let location: CliLocation | undefined;
    let text: string | undefined;
    let terminatedByQuit = false;

    for (const rawCommand of commandSegments) {
      if (terminatedByQuit) {
        return this._handleCommandFailure(commandSegments.length, commandResults, {
          command: rawCommand,
          sessionId,
          threadId,
          frameIndex,
          location,
          message: "No active session. The previous 'quit' command terminated the selected session.",
        });
      }

      let parsed: ParsedCommand;
      try {
        parsed = this._parseCommand(rawCommand);
      } catch (err) {
        return this._handleCommandFailure(commandSegments.length, commandResults, {
          command: rawCommand,
          sessionId,
          threadId,
          frameIndex,
          location,
          message: err instanceof Error ? err.message : String(err),
        });
      }

      try {
        const result = await this._executeCommand(parsed, { sessionId, threadId }, token);
        commandResults.push(result.command);
        sessionId = result.sessionId ?? sessionId;
        threadId = result.threadId ?? threadId;
        frameIndex = result.frameIndex;
        location = result.location ?? location;
        text = result.text ?? text;
        terminatedByQuit = parsed.verb === 'quit';
      } catch (err) {
        return this._handleCommandFailure(commandSegments.length, commandResults, {
          command: parsed.raw,
          sessionId,
          threadId,
          frameIndex,
          location,
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }

    return this._cliResult({
      sessionId,
      threadId,
      frameIndex,
      location,
      commands: commandResults,
      text,
    });
  }

  private async _executeCommand(
    parsed: ParsedCommand,
    context: { sessionId?: string; threadId?: number },
    token: vscode.CancellationToken,
  ): Promise<CliExecutionResult> {
    switch (parsed.verb) {
      case 'help':
        return this._handleHelp(parsed);
      case 'run':
        return await this._handleRun(parsed, token);
      case 'break':
        return await this._handleBreak(parsed, context.sessionId);
      case 'clear':
        return await this._handleClear(parsed, context.sessionId);
      case 'disable':
        return await this._handleBreakpointEnabled(parsed, context.sessionId, false);
      case 'enable':
        return await this._handleBreakpointEnabled(parsed, context.sessionId, true);
      case 'continue':
      case 'next':
      case 'step':
      case 'finish':
      case 'quit':
        return await this._handleExecution(parsed, context.sessionId, context.threadId, token);
      case 'print':
        return await this._handlePrint(parsed, context.sessionId, context.threadId);
      case 'where':
        return await this._handleWhere(parsed, context.sessionId, context.threadId);
      case 'locals':
        return await this._handleLocals(parsed, context.sessionId, context.threadId);
      case 'globals':
        return await this._handleGlobals(parsed, context.sessionId, context.threadId);
      case 'list':
        return await this._handleList(parsed, context.sessionId, context.threadId);
      case 'up':
      case 'down':
      case 'frame':
        return await this._handleFrameNavigation(parsed, context.sessionId, context.threadId);
      default:
        throw new Error(`Command '${parsed.verb}' is not supported in this version.`);
    }
  }

  private _handleCommandFailure(
    commandCount: number,
    successfulCommands: CliCommandResult[],
    failure: {
      command: string;
      sessionId?: string;
      threadId?: number;
      frameIndex: number;
      location?: CliLocation;
      message: string;
    },
  ): vscode.LanguageModelToolResult {
    if (successfulCommands.length === 0 && commandCount === 1) {
      return errorResult(failure.message);
    }

    return this._cliResult({
      sessionId: failure.sessionId,
      threadId: failure.threadId,
      frameIndex: failure.frameIndex,
      location: failure.location,
      commands: [
        ...successfulCommands,
        {
          command: failure.command,
          status: 'error',
          summary: failure.message,
          error: failure.message,
        },
      ],
    });
  }

  private _handleHelp(parsed: ParsedCommand): CliExecutionResult {
    this._assertNoArgument(parsed);

    return {
      frameIndex: 0,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: 'CLI help for Dapper agent tools',
        result: {
          phase: 1,
          chainingSupported: true,
          commandStyle: 'pdb-like',
          commands: CLI_COMMAND_HELP,
          tools: this.underlyingToolHelp,
        },
      },
      text: this._renderHelpText(),
    };
  }

  private async _handleRun(
    parsed: ParsedCommand,
    token: vscode.CancellationToken,
  ): Promise<CliExecutionResult> {
    this._assertNoArgument(parsed);

    if (this.registry.journals.size > 0) {
      throw new Error("'run' is only available when no Dapper session is active. Terminate the existing session first or use dapper_launch.");
    }

    const payload = await this._invokeJson(this.launchTool, {
      target: { currentFile: true },
      waitForStop: true,
    }, token) as JsonObject;

    const sessionId = asString(payload?.sessionId);
    if (!sessionId) {
      throw new Error('Run did not create a Dapper session.');
    }

    const state = this._stateFor(sessionId);
    state.frameIndex = 0;
    const snapshot = payload?.snapshot as SnapshotLike | null | undefined;
    const location = this._captureLocation(sessionId, snapshot ?? undefined);
    const summary = location
      ? `Started and stopped at ${this._formatLocation(location)}`
      : 'Started Dapper debug session';

    return {
      sessionId,
      threadId: asNumber(snapshot?.threadId),
      frameIndex: state.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary,
        result: {
          started: payload?.started === true,
          waitedForStop: payload?.waitedForStop === true,
          stopped: payload?.stopped === true,
          configuration: payload?.configuration ?? null,
        },
      },
    };
  }

  private async _handleBreak(
    parsed: ParsedCommand,
    sessionId?: string,
  ): Promise<CliExecutionResult> {
    const target = parsed.arg?.trim();
    if (!target) {
      throw new Error("'break' requires a breakpoint target such as app.py:65.");
    }

    const { file, line } = await this._resolveBreakpointTarget(target, sessionId);
    const breakpointPayload = await this._invokeJson(this.breakpointsTool, {
      action: 'add',
      sessionId,
      file,
      lines: [line],
    }) as JsonObject;

    const location: CliLocation = {
      file,
      line,
    };
    return {
      sessionId,
      frameIndex: 0,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `Breakpoint set at ${this._formatLocation(location)}`,
        result: breakpointPayload,
      },
    };
  }

  private async _handleClear(
    parsed: ParsedCommand,
    sessionId?: string,
  ): Promise<CliExecutionResult> {
    const selected = parsed.arg?.trim() ? this._trySelectSession(sessionId) : this._requireSingleSession(sessionId);
    const state = selected ? this._stateFor(selected.sessionId) : undefined;
    const target = await this._parseBreakpointSelection(
      parsed.arg,
      state?.lastKnownLocation,
      'clear',
      selected?.sessionId,
      state?.threadId,
    );
    const action = target.line === undefined ? 'clear' : 'remove';
    const payload = await this._invokeJson(this.breakpointsTool, {
      sessionId: selected?.sessionId,
      action,
      file: target.file,
      lines: target.line === undefined ? undefined : [target.line],
    }) as JsonObject;

    const removed = asNumber(payload.removed) ?? 0;
    return {
      sessionId: selected?.sessionId,
      threadId: state?.threadId,
      frameIndex: state?.frameIndex ?? 0,
      location: target.line === undefined ? state?.lastKnownLocation : { file: target.file, line: target.line },
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: target.line === undefined
          ? `Cleared ${removed} breakpoint(s) in ${vscode.workspace.asRelativePath(target.file, false)}`
          : `Cleared breakpoint at ${vscode.workspace.asRelativePath(target.file, false)}:${target.line}`,
        result: payload,
      },
    };
  }

  private async _handleBreakpointEnabled(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    enabled: boolean,
  ): Promise<CliExecutionResult> {
    const selected = parsed.arg?.trim() ? this._trySelectSession(sessionId) : this._requireSingleSession(sessionId);
    const state = selected ? this._stateFor(selected.sessionId) : undefined;
    const target = await this._parseBreakpointSelection(
      parsed.arg,
      state?.lastKnownLocation,
      enabled ? 'enable' : 'disable',
      selected?.sessionId,
      state?.threadId,
    );
    const payload = await this._invokeJson(this.breakpointsTool, {
      sessionId: selected?.sessionId,
      action: enabled ? 'enable' : 'disable',
      file: target.file,
      lines: target.line === undefined ? undefined : [target.line],
    }) as JsonObject;

    const updated = asNumber(payload.updated) ?? 0;
    return {
      sessionId: selected?.sessionId,
      threadId: state?.threadId,
      frameIndex: state?.frameIndex ?? 0,
      location: target.line === undefined ? state?.lastKnownLocation : { file: target.file, line: target.line },
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: target.line === undefined
          ? `${enabled ? 'Enabled' : 'Disabled'} ${updated} breakpoint(s) in ${vscode.workspace.asRelativePath(target.file, false)}`
          : `${enabled ? 'Enabled' : 'Disabled'} breakpoint at ${vscode.workspace.asRelativePath(target.file, false)}:${target.line}`,
        result: payload,
      },
    };
  }

  private async _handleExecution(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
    token: vscode.CancellationToken,
  ): Promise<CliExecutionResult> {
    this._assertNoArgument(parsed);
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const threadId = requestedThreadId ?? state.threadId;

    if (parsed.verb === 'quit') {
      const payload = await this._invokeJson(this.executionTool, {
        sessionId: selected.sessionId,
        action: 'terminate',
      }, token) as JsonObject;
      this.sessionState.delete(selected.sessionId);
      return {
        sessionId: selected.sessionId,
        threadId,
        frameIndex: state.frameIndex,
        location: state.lastKnownLocation,
        command: {
          command: parsed.raw,
          status: 'ok',
          summary: 'Terminating debug session',
          result: payload,
        },
      };
    }

    const action = executionActionFor(parsed.verb as 'continue' | 'next' | 'step' | 'finish');
    const payload = await this._invokeJson(this.executionTool, {
      sessionId: selected.sessionId,
      action,
      threadId,
      report: true,
    }, token) as JsonObject;

    const snapshot = payload?.snapshot as SnapshotLike | null | undefined;
    const effectiveThreadId = asNumber(snapshot?.threadId) ?? threadId;
    if (payload?.stopped === true) {
      state.frameIndex = 0;
    }
    const location = this._captureLocation(selected.sessionId, snapshot ?? undefined);
    const summary = payload?.stopped === true && location
      ? `Stopped at ${this._formatLocation(location)}`
      : payload?.stopped === true
        ? 'Stopped'
        : 'Execution resumed';

    return {
      sessionId: selected.sessionId,
      threadId: effectiveThreadId,
      frameIndex: state.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary,
        result: {
          action,
          stopped: payload?.stopped === true,
          checkpointBefore: payload?.checkpointBefore ?? null,
          checkpointAfter: payload?.checkpointAfter ?? null,
          diff: payload?.diff ?? null,
        },
      },
    };
  }

  private async _handlePrint(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    const expression = parsed.arg?.trim();
    if (!expression) {
      throw new Error("'print' requires an expression.");
    }

    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const payload = await this._invokeJson(this.evaluateTool, {
      sessionId: selected.sessionId,
      expression,
      frameIndex: state.frameIndex,
    });

    const first = Array.isArray(payload) ? payload[0] as JsonObject | undefined : undefined;
    if (!first) {
      throw new Error('Evaluation returned no result.');
    }
    if (typeof first.error === 'string' && first.error) {
      throw new Error(first.error);
    }

    const result = {
      expression,
      type: asString(first.type) ?? '',
      value: asString(first.result) ?? '',
    };

    return {
      sessionId: selected.sessionId,
      threadId: requestedThreadId ?? state.threadId,
      frameIndex: state.frameIndex,
      location: state.lastKnownLocation,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `${expression} = ${String(result.value)}`,
        result,
      },
    };
  }

  private async _handleWhere(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    this._assertNoArgument(parsed);
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, requestedThreadId ?? state.threadId);
    const frameContext = this._frameContext(selected.sessionId, snapshot);
    const location = this._captureLocation(selected.sessionId, snapshot);
    const frames = frameContext.callStack.map((frame, index) => ({
      ...frame,
      frameIndex: index,
      selected: index === frameContext.frameIndex,
    }));

    return {
      sessionId: selected.sessionId,
      threadId: asNumber(snapshot.threadId) ?? requestedThreadId ?? state.threadId,
      frameIndex: frameContext.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: frames.length > 0
          ? `Call stack has ${frames.length} frame(s); selected frame is #${frameContext.frameIndex} ${frameContext.frame?.name ?? '<unknown>'}`
          : 'Call stack is empty',
        result: {
          selectedFrameIndex: frameContext.frameIndex,
          frames,
        },
      },
    };
  }

  private async _handleLocals(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    this._assertNoArgument(parsed);
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, requestedThreadId ?? state.threadId);
    const frameContext = this._frameContext(selected.sessionId, snapshot);
    const location = this._captureLocation(selected.sessionId, snapshot);
    const locals = await this._getScopeVariables(selected.sessionId, 'locals', frameContext.frameIndex, snapshot);

    return {
      sessionId: selected.sessionId,
      threadId: asNumber(snapshot.threadId) ?? requestedThreadId ?? state.threadId,
      frameIndex: frameContext.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `Locals: ${Object.keys(locals).length} name(s)`,
        result: locals,
      },
    };
  }

  private async _handleGlobals(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    this._assertNoArgument(parsed);
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, requestedThreadId ?? state.threadId);
    const frameContext = this._frameContext(selected.sessionId, snapshot);
    const location = this._captureLocation(selected.sessionId, snapshot);
    const globals = await this._getScopeVariables(selected.sessionId, 'globals', frameContext.frameIndex, snapshot);

    return {
      sessionId: selected.sessionId,
      threadId: asNumber(snapshot.threadId) ?? requestedThreadId ?? state.threadId,
      frameIndex: frameContext.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `Globals: ${Object.keys(globals).length} name(s)`,
        result: globals,
      },
    };
  }

  private async _handleList(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, requestedThreadId ?? state.threadId);
    const frameContext = this._frameContext(selected.sessionId, snapshot);
    const location = this._captureLocation(selected.sessionId, snapshot);
    if (!frameContext.frame?.file || typeof frameContext.frame.line !== 'number') {
      throw new Error('The selected frame does not have a source location to list.');
    }

    const source = await fs.promises.readFile(frameContext.frame.file, 'utf8');
    const allLines = source.split(/\r?\n/);
    const range = this._resolveListRange(parsed.arg, frameContext.frame.line, allLines.length);
    const lines = allLines.slice(range.startLine - 1, range.endLine).map((text, index) => {
      const lineNumber = range.startLine + index;
      return {
        line: lineNumber,
        text,
        current: lineNumber === frameContext.frame?.line,
      };
    });

    return {
      sessionId: selected.sessionId,
      threadId: asNumber(snapshot.threadId) ?? requestedThreadId ?? state.threadId,
      frameIndex: frameContext.frameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `Listed ${lines.length} line(s) from ${vscode.workspace.asRelativePath(frameContext.frame.file, false)}`,
        result: {
          file: frameContext.frame.file,
          currentLine: frameContext.frame.line,
          startLine: range.startLine,
          endLine: range.endLine,
          lines,
        },
      },
    };
  }

  private async _handleFrameNavigation(
    parsed: ParsedCommand,
    sessionId: string | undefined,
    requestedThreadId: number | undefined,
  ): Promise<CliExecutionResult> {
    const selected = this._requireSingleSession(sessionId);
    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, requestedThreadId ?? state.threadId);
    const frameContext = this._frameContext(selected.sessionId, snapshot);

    if (frameContext.callStack.length === 0) {
      throw new Error('Call stack is empty.');
    }

    let nextFrameIndex = frameContext.frameIndex;
    switch (parsed.verb) {
      case 'up':
        this._assertNoArgument(parsed);
        if (frameContext.frameIndex >= frameContext.callStack.length - 1) {
          throw new Error('Already at the oldest frame.');
        }
        nextFrameIndex += 1;
        break;
      case 'down':
        this._assertNoArgument(parsed);
        if (frameContext.frameIndex <= 0) {
          throw new Error('Already at the newest frame.');
        }
        nextFrameIndex -= 1;
        break;
      case 'frame': {
        const arg = parsed.arg?.trim();
        if (!arg) {
          throw new Error("'frame' requires a zero-based frame index.");
        }
        const parsedIndex = Number.parseInt(arg, 10);
        if (!Number.isInteger(parsedIndex) || parsedIndex < 0 || parsedIndex >= frameContext.callStack.length) {
          throw new Error(`Frame index '${arg}' is invalid. Valid range: 0-${frameContext.callStack.length - 1}.`);
        }
        nextFrameIndex = parsedIndex;
        break;
      }
    }

    state.frameIndex = nextFrameIndex;
    const location = this._captureLocation(selected.sessionId, snapshot);
    const frame = frameContext.callStack[nextFrameIndex];

    return {
      sessionId: selected.sessionId,
      threadId: asNumber(snapshot.threadId) ?? requestedThreadId ?? state.threadId,
      frameIndex: nextFrameIndex,
      location,
      command: {
        command: parsed.raw,
        status: 'ok',
        summary: `Selected frame #${nextFrameIndex}: ${frame?.name ?? '<unknown>'}`,
        result: {
          selectedFrameIndex: nextFrameIndex,
          frameCount: frameContext.callStack.length,
          frame,
        },
      },
    };
  }

  private _splitCommands(command: string): string[] {
    const commands = command
      .split(';')
      .map(part => part.trim())
      .filter(part => part.length > 0);
    if (commands.length === 0) {
      throw new Error('No command provided.');
    }
    return commands;
  }

  private async _getSnapshot(sessionId: string, threadId?: number): Promise<SnapshotLike> {
    return await this._invokeJson(this.stateTool, {
      sessionId,
      mode: 'snapshot',
      threadId,
    }) as SnapshotLike;
  }

  private _trySelectSession(sessionId?: string): SessionSelection | undefined {
    if (!sessionId) {
      return undefined;
    }

    const journal = this.registry.resolve(sessionId);
    return journal ? { sessionId, session: journal.session } : undefined;
  }

  private _requireSingleSession(sessionId?: string): SessionSelection {
    if (sessionId) {
      const journal = this.registry.resolve(sessionId);
      if (!journal) {
        throw new Error(`No Dapper session found for sessionId '${sessionId}'.`);
      }
      return { sessionId, session: journal.session };
    }

    const journals = Array.from(this.registry.journals.values());
    if (journals.length === 0) {
      throw new Error("No active session. Run 'run' first or specify a sessionId.");
    }
    if (journals.length > 1) {
      throw new Error('Multiple active Dapper sessions found. Specify sessionId.');
    }
    const journal = journals[0];
    return { sessionId: journal.sessionId, session: journal.session };
  }

  private async _resolveBreakpointTarget(
    target: string,
    sessionId?: string,
    threadId?: number,
  ): Promise<{ file: string; line: number }> {
    const lastColon = target.lastIndexOf(':');
    if (lastColon <= 0 || lastColon === target.length - 1) {
      throw new Error(`Breakpoint target '${target}' is invalid. Expected file:line or function:line.`);
    }

    const targetPart = target.slice(0, lastColon).trim();
    const linePart = target.slice(lastColon + 1).trim();
    const line = Number.parseInt(linePart, 10);
    if (!Number.isInteger(line) || line <= 0) {
      throw new Error(`Breakpoint target '${target}' is invalid. Expected file:line or function:line.`);
    }

    const directFile = this._resolveFilePath(targetPart);
    if (directFile) {
      return { file: directFile, line };
    }

    const workspaceFile = this._resolveWorkspacePythonStem(targetPart);
    if (workspaceFile) {
      return { file: workspaceFile, line };
    }

    const functionFile = await this._resolveFunctionTarget(targetPart, sessionId, threadId);
    if (functionFile) {
      return { file: functionFile, line };
    }

    throw new Error(`Breakpoint target '${target}' is invalid. Expected file:line or function:line.`);
  }

  private async _parseBreakpointSelection(
    target: string | undefined,
    defaultLocation: CliLocation | undefined,
    commandName: string,
    sessionId?: string,
    threadId?: number,
  ): Promise<{ file: string; line?: number }> {
    const trimmed = target?.trim();
    if (!trimmed) {
      if (!defaultLocation) {
        throw new Error(`'${commandName}' requires a breakpoint target such as app.py:65 when no current location is selected.`);
      }
      return { file: defaultLocation.file, line: defaultLocation.line };
    }

    if (trimmed.includes(':')) {
      return await this._resolveBreakpointTarget(trimmed, sessionId, threadId);
    }

    const file = this._resolveFilePath(trimmed) ?? this._resolveWorkspacePythonStem(trimmed);
    if (!file) {
      throw new Error(`Breakpoint target '${trimmed}' is invalid. Expected file, file:line, or function:line.`);
    }
    return { file };
  }

  private _resolveFilePath(file: string): string | undefined {
    if (path.isAbsolute(file)) {
      return fs.existsSync(file) ? file : undefined;
    }

    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      const candidate = path.join(folder.uri.fsPath, file);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }

    return undefined;
  }

  private _resolveWorkspacePythonStem(target: string): string | undefined {
    const folders = vscode.workspace.workspaceFolders ?? [];
    const matches = new Set<string>();

    for (const folder of folders) {
      this._collectPythonStemMatches(folder.uri.fsPath, target, matches);
    }

    if (matches.size > 1) {
      const matchList = Array.from(matches).map(match => vscode.workspace.asRelativePath(match, false)).join(', ');
      throw new Error(`Breakpoint target '${target}' is ambiguous. Matches: ${matchList}. Use a path.`);
    }

    return Array.from(matches)[0];
  }

  private _collectPythonStemMatches(rootPath: string, target: string, matches: Set<string>): void {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(rootPath, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (entry.name === '.git' || entry.name === 'node_modules' || entry.name === '__pycache__') {
        continue;
      }

      const fullPath = path.join(rootPath, entry.name);
      if (entry.isDirectory()) {
        this._collectPythonStemMatches(fullPath, target, matches);
        continue;
      }

      if (!entry.isFile()) {
        continue;
      }

      if (path.extname(entry.name) !== '.py') {
        continue;
      }

      const basename = path.basename(entry.name, '.py');
      if (entry.name === target || basename === target) {
        matches.add(fullPath);
      }
    }
  }

  private async _resolveFunctionTarget(
    functionName: string,
    sessionId?: string,
    threadId?: number,
  ): Promise<string | undefined> {
    const selected = this._selectSessionForBreakpointResolution(sessionId);
    if (!selected) {
      return undefined;
    }

    const state = this._stateFor(selected.sessionId);
    const snapshot = await this._getSnapshot(selected.sessionId, threadId ?? state.threadId);
    const frames = Array.isArray(snapshot.callStack) ? snapshot.callStack : [];
    const matches = new Set(
      frames
        .filter(frame => frame.name === functionName && typeof frame.file === 'string' && frame.file.length > 0)
        .map(frame => frame.file as string),
    );

    if (matches.size > 1) {
      const matchList = Array.from(matches).map(match => vscode.workspace.asRelativePath(match, false)).join(', ');
      throw new Error(`Breakpoint target '${functionName}' is ambiguous. Matches functions in: ${matchList}. Use a file path.`);
    }

    const file = Array.from(matches)[0];
    if (file) {
      return file;
    }

    const lastKnownLocation = this._stateFor(selected.sessionId).lastKnownLocation;
    if (lastKnownLocation?.function === functionName) {
      return lastKnownLocation.file;
    }

    return undefined;
  }

  private _selectSessionForBreakpointResolution(sessionId?: string): SessionSelection | undefined {
    if (sessionId) {
      const journal = this.registry.resolve(sessionId);
      if (!journal) {
        throw new Error(`No Dapper session found for sessionId '${sessionId}'.`);
      }
      return { sessionId, session: journal.session };
    }

    const journals = Array.from(this.registry.journals.values());
    if (journals.length === 1) {
      const journal = journals[0];
      return { sessionId: journal.sessionId, session: journal.session };
    }

    return undefined;
  }

  private _parseCommand(command: string): ParsedCommand {
    const firstSpace = command.search(/\s/);
    const rawVerb = firstSpace >= 0 ? command.slice(0, firstSpace) : command;
    const arg = firstSpace >= 0 ? command.slice(firstSpace).trimStart() : undefined;
    const verb = COMMAND_ALIASES[rawVerb];
    if (!verb) {
      throw new Error(`Command '${rawVerb}' is not supported in this version.`);
    }
    return { raw: command, verb, arg };
  }

  private _renderHelpText(): string {
    const commandLines = CLI_COMMAND_HELP.map(command => {
      const aliases = command.aliases.length > 0 ? ` (${command.aliases.join(', ')})` : '';
      const args = command.args === 'none' ? '' : ` ${command.args}`;
      return `${command.command}${aliases}${args} - ${command.description}`;
    });
    const toolLines = this.underlyingToolHelp.flatMap(tool => {
      const header = `${tool.name} (${tool.displayName}): ${tool.purpose}`;
      const args = tool.arguments.map(arg => {
        const required = arg.required ? 'required' : 'optional';
        return `  - ${arg.name} (${required}): ${arg.description}`;
      });
      return [header, ...args];
    });

    return [
      'Dapper CLI works like pdb for common debugger actions.',
      'Phase 1 supports semicolon-chained command sequences plus frame navigation and basic breakpoint state changes.',
      '',
      'CLI commands:',
      ...commandLines,
      '',
      'Underlying Dapper tools:',
      ...toolLines,
      '',
      'Common input context:',
      '  - sessionId (optional): required when multiple Dapper sessions are active.',
      '  - threadId (optional): selects the target thread for execution or inspection commands.',
    ].join('\n');
  }

  private _assertNoArgument(parsed: ParsedCommand): void {
    if (parsed.arg && parsed.arg.trim()) {
      throw new Error(`Command '${parsed.verb}' does not accept arguments in Phase 1.`);
    }
  }

  private _stateFor(sessionId: string): SessionState {
    let state = this.sessionState.get(sessionId);
    if (!state) {
      state = { frameIndex: 0 };
      this.sessionState.set(sessionId, state);
    }
    return state;
  }

  private _captureLocation(sessionId: string, snapshot?: SnapshotLike): CliLocation | undefined {
    const state = this._stateFor(sessionId);
    if (!snapshot) {
      return state.lastKnownLocation;
    }

    const threadId = asNumber(snapshot.threadId);
    if (threadId !== undefined) {
      state.threadId = threadId;
    }

    const frame = this._frameContext(sessionId, snapshot).frame;
    let location: CliLocation | undefined;
    if (frame?.file && typeof frame.line === 'number') {
      location = {
        file: frame.file,
        line: frame.line,
        function: frame.name,
      };
    } else if (typeof snapshot.location === 'string') {
      location = parseLocationString(snapshot.location);
    }

    if (location) {
      state.lastKnownLocation = location;
    }
    return location ?? state.lastKnownLocation;
  }

  private _frameContext(sessionId: string, snapshot: SnapshotLike): {
    state: SessionState;
    callStack: Array<{ name?: string; file?: string; line?: number }>;
    frameIndex: number;
    frame?: { name?: string; file?: string; line?: number };
  } {
    const state = this._stateFor(sessionId);
    const callStack = Array.isArray(snapshot.callStack) ? snapshot.callStack : [];
    if (callStack.length === 0) {
      state.frameIndex = 0;
      return { state, callStack, frameIndex: 0, frame: undefined };
    }

    state.frameIndex = Math.min(Math.max(state.frameIndex, 0), callStack.length - 1);
    return {
      state,
      callStack,
      frameIndex: state.frameIndex,
      frame: callStack[state.frameIndex],
    };
  }

  private async _getScopeVariables(
    sessionId: string,
    scope: 'locals' | 'globals',
    frameIndex: number,
    snapshot: SnapshotLike,
  ): Promise<Record<string, string>> {
    if (frameIndex === 0) {
      return scope === 'locals' ? snapshot.locals ?? {} : snapshot.globals ?? {};
    }

    const root = await this._invokeJson(this.inspectVariableTool, {
      sessionId,
      expression: `${scope}()`,
      depth: 1,
      maxItems: 200,
      frameIndex,
    }) as InspectNodeLike | undefined;
    return inspectChildrenToVariables(root);
  }

  private _resolveListRange(
    arg: string | undefined,
    currentLine: number,
    totalLines: number,
  ): { startLine: number; endLine: number } {
    const trimmed = arg?.trim();
    if (!trimmed) {
      return clampLineRange(currentLine - 5, currentLine + 5, totalLines);
    }

    const parts = trimmed.split(',').map(part => part.trim()).filter(part => part.length > 0);
    if (parts.length === 1) {
      const startLine = Number.parseInt(parts[0], 10);
      if (!Number.isInteger(startLine) || startLine <= 0) {
        throw new Error(`List range '${trimmed}' is invalid. Use 'list', 'list 25', or 'list 25,35'.`);
      }
      return clampLineRange(startLine, startLine + 10, totalLines);
    }

    if (parts.length === 2) {
      const startLine = Number.parseInt(parts[0], 10);
      const endLine = Number.parseInt(parts[1], 10);
      if (!Number.isInteger(startLine) || !Number.isInteger(endLine) || startLine <= 0 || endLine < startLine) {
        throw new Error(`List range '${trimmed}' is invalid. Use 'list', 'list 25', or 'list 25,35'.`);
      }
      return clampLineRange(startLine, endLine, totalLines);
    }

    throw new Error(`List range '${trimmed}' is invalid. Use 'list', 'list 25', or 'list 25,35'.`);
  }

  private _formatLocation(location: CliLocation): string {
    const relative = vscode.workspace.asRelativePath(location.file, false);
    const functionSuffix = location.function ? ` in ${location.function}` : '';
    return `${relative}:${location.line}${functionSuffix}`;
  }

  private async _invokeJson<TInput>(
    tool: vscode.LanguageModelTool<TInput>,
    input: TInput,
    token?: vscode.CancellationToken,
  ): Promise<unknown> {
    const result = await tool.invoke(
      { input } as vscode.LanguageModelToolInvocationOptions<TInput>,
      token ?? ({ isCancellationRequested: false } as vscode.CancellationToken),
    );
    if (!result) {
      return undefined;
    }
    const raw = resultText(result).trim();
    if (raw.startsWith('Error: ')) {
      throw new Error(raw.slice('Error: '.length));
    }
    return raw ? JSON.parse(raw) : undefined;
  }

  private _cliResult(payload: {
    sessionId?: string;
    threadId?: number;
    frameIndex: number;
    location?: CliLocation;
    commands: CliCommandResult[];
    text?: string;
  }): vscode.LanguageModelToolResult {
    const text = payload.text ?? payload.commands.map(command => command.summary).join('\n');
    return jsonResult({
      sessionId: payload.sessionId ?? null,
      threadId: payload.threadId ?? null,
      frameIndex: payload.frameIndex,
      location: payload.location ?? null,
      commands: payload.commands,
      text,
    });
  }
}

function executionActionFor(verb: Extract<CliVerb, 'continue' | 'next' | 'step' | 'finish'>): 'continue' | 'next' | 'stepIn' | 'stepOut' {
  switch (verb) {
    case 'continue':
      return 'continue';
    case 'next':
      return 'next';
    case 'step':
      return 'stepIn';
    case 'finish':
      return 'stepOut';
  }
}

function parseLocationString(location: string): CliLocation | undefined {
  const match = /^(.*):(\d+)(?: in (.*))?$/.exec(location);
  if (!match) {
    return undefined;
  }
  return {
    file: match[1],
    line: Number.parseInt(match[2], 10),
    function: match[3],
  };
}

function resultText(result: vscode.LanguageModelToolResult): string {
  const content = Array.isArray((result as { content?: unknown[] }).content)
    ? (result as { content: Array<{ value?: string }> }).content
    : [];
  return content.map(part => part.value ?? '').join('');
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined;
}

function inspectChildrenToVariables(root: InspectNodeLike | undefined): Record<string, string> {
  const variables: Record<string, string> = {};
  for (const child of root?.children ?? []) {
    if (typeof child.name === 'string') {
      variables[child.name] = typeof child.value === 'string' ? child.value : '';
    }
  }
  return variables;
}

function clampLineRange(startLine: number, endLine: number, totalLines: number): { startLine: number; endLine: number } {
  const maxLine = Math.max(totalLines, 1);
  const clampedStart = Math.min(Math.max(startLine, 1), maxLine);
  const clampedEnd = Math.min(Math.max(endLine, clampedStart), maxLine);
  return {
    startLine: clampedStart,
    endLine: clampedEnd,
  };
}

function buildUnderlyingToolHelp(packageManifest: ExtensionPackageManifest): ToolHelpEntry[] {
  const toolEntries = Array.isArray(packageManifest.contributes?.languageModelTools)
    ? packageManifest.contributes.languageModelTools
    : [];
  const entries = toolEntries.filter(isToolManifestEntry);

  return entries.map((entry) => {
    const required = new Set(entry.inputSchema?.required ?? []);
    const properties = entry.inputSchema?.properties ?? {};
    const argumentEntries = Object.entries(properties).map(([name, property]) => ({
      name,
      required: required.has(name),
      description: property?.description ?? 'No description provided.',
    }));

    return {
      name: entry.name,
      displayName: entry.displayName ?? entry.name,
      purpose: entry.modelDescription ?? 'No model description provided.',
      arguments: argumentEntries,
    } satisfies ToolHelpEntry;
  });
}

function isToolManifestEntry(value: unknown): value is ToolManifestEntry {
  return typeof value === 'object'
    && value !== null
    && typeof (value as { name?: unknown }).name === 'string';
}