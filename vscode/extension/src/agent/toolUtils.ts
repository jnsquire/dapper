/**
 * Shared helpers for resolving debug sessions used by all agent tools.
 */

import * as vscode from 'vscode';
import type { JournalRegistry, StateJournal } from './stateJournal.js';

/**
 * Resolve a debug session and its journal from an optional sessionId.
 * Falls back to the active Dapper session.
 */
export function resolveSession(
  registry: JournalRegistry,
  sessionId?: string,
): { session: vscode.DebugSession; journal: StateJournal } | undefined {
  const journal = registry.resolve(sessionId);
  if (!journal) return undefined;

  // Look up the actual DebugSession object
  if (sessionId) {
    // The journal tracks the session
    const session = findDapperSession(sessionId);
    if (session) return { session, journal };
  }

  const active = vscode.debug.activeDebugSession;
  if (active?.type === 'dapper') {
    return { session: active, journal };
  }

  return undefined;
}

function findDapperSession(sessionId: string): vscode.DebugSession | undefined {
  // vscode.debug doesn't expose a "get session by id" API, but the journal
  // was created from the session object in the tracker factory, so we can
  // rely on the active session or iterate known sessions.
  const active = vscode.debug.activeDebugSession;
  if (active?.id === sessionId) return active;
  return undefined;
}

/**
 * Create a text-only LanguageModelToolResult.
 */
export function textResult(content: string): vscode.LanguageModelToolResult {
  return new vscode.LanguageModelToolResult([
    new vscode.LanguageModelTextPart(content),
  ]);
}

/**
 * Create a JSON LanguageModelToolResult (serialised as readable text).
 */
export function jsonResult(data: unknown): vscode.LanguageModelToolResult {
  return textResult(JSON.stringify(data, null, 2));
}

/**
 * Create an error LanguageModelToolResult.
 */
export function errorResult(message: string): vscode.LanguageModelToolResult {
  return textResult(`Error: ${message}`);
}
