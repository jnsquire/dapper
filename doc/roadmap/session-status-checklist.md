# Session Status and Breakpoint Readiness Checklist

## Goal

Replace vague unknown debugger state with explicit session readiness, breakpoint lifecycle visibility, and actionable error reporting.

## Implementation Map

- [ ] Session lifecycle and readiness state in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts)
- [ ] Session status tool in [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts) and registration in [vscode/extension/src/agent/tools/index.ts](../../vscode/extension/src/agent/tools/index.ts)
- [ ] Breakpoint lifecycle aggregation in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts)
- [ ] Bootstrap and ready-wait flow in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts)
- [ ] Session-state plumbing and custom request handling in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts)
- [ ] Launch-time waiting and readiness checks in [vscode/extension/src/debugAdapter/launchService.ts](../../vscode/extension/src/debugAdapter/launchService.ts)
- [ ] Debug adapter registration wiring in [vscode/extension/src/extension.ts](../../vscode/extension/src/extension.ts)

## Work Breakdown

### PR 1: Add session readiness data (stateJournal only)

**Commit 1 — types**
- [ ] Add `SessionLifecycleState` union type (`initializing | waiting-for-breakpoints | ready | running | stopped | error | unknown`) to [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Add `SessionReadinessInfo` interface (`lifecycleState`, `breakpointRegistrationComplete`, `lastTransition`, `lastError`) to [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).

**Commit 2 — tracking logic**
- [ ] Add private `_lifecycleState`, `_breakpointRegistrationComplete`, `_lastTransition`, and `_lastReadinessError` fields to `StateJournal` in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Expose a `readinessInfo` getter on `StateJournal` that returns a `SessionReadinessInfo` snapshot.
- [ ] Drive state transitions from the existing `onDidSendMessage` handler (e.g. `initialized` event → ready, `breakpoint` event → update registration flag).

**Commit 3 — tests**
- [ ] Add tests for lifecycle state transitions in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts).
- [ ] Add tests for `breakpointRegistrationComplete` toggling in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts).
- [ ] Add a test that `lastError` is set when the adapter sends a failure event and cleared when the session recovers.

---

### PR 2: Enrich dapper_session_info

**Commit 1 — new tool file**
- [ ] Extend [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts) so `dapper_session_info` returns the richer readiness and breakpoint lifecycle output.
- [ ] Define `SessionStatusOutput` interface: `lifecycleState`, `breakpointRegistrationComplete`, `breakpoints.accepted`, `breakpoints.pending`, `breakpoints.rejected`, `lastTransition`, `lastError`, `readyToContinue`.
- [ ] Populate the output from `journal.readinessInfo` and a breakpoint count pass over the existing `_breakpointVerification` map.

**Commit 2 — registration**
- [ ] Keep only `dapper_session_info` registered in [vscode/extension/src/agent/tools/index.ts](../../vscode/extension/src/agent/tools/index.ts) so callers have a single session-inspection surface.

**Commit 3 — tests**
- [ ] Add tests in [vscode/extension/test/sessionInfoTool.test.ts](../../vscode/extension/test/sessionInfoTool.test.ts) covering the happy path, the no-session error path, and the not-ready case.

---

### PR 3: Improve breakpoint lifecycle reporting

**Commit 1 — initialize pending state eagerly**
- [ ] When `_syncBreakpoints` sends a `setBreakpoints` request in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts), mark all requested lines as `pending` in the journal before awaiting the response.

**Commit 2 — preserve rejection messages**
- [ ] Store the full adapter message on rejected breakpoints in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts) instead of discarding it.
- [ ] Add `rejectionReason` to `BreakpointInfo` in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts) and populate it in the `list` action.

**Commit 3 — aggregate counts**
- [ ] Add a `getBreakpointStatusCounts()` method to `StateJournal` in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts) returning `{ verified, pending, rejected }` totals.
- [ ] Use this method in `GetSessionInfoTool` (PR 2) for the `breakpoints` field.

**Commit 4 — tests**
- [ ] Add a test for `pending` → `verified` transition in [vscode/extension/test/breakpointsTool.test.ts](../../vscode/extension/test/breakpointsTool.test.ts).
- [ ] Add a test for `pending` → `rejected` transition with message preservation in [vscode/extension/test/breakpointsTool.test.ts](../../vscode/extension/test/breakpointsTool.test.ts).
- [ ] Add a test for `getBreakpointStatusCounts()` returning correct totals in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts).

---

### PR 4: Add readiness gating in the bootstrap

**Commit 1 — wait helper**
- [ ] Add `waitForBreakpointsInstalled(journal: StateJournal, timeoutMs: number): Promise<BreakpointReadinessResult>` in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts) or a new shared helper file.
- [ ] Define `BreakpointReadinessResult` with `ready: boolean`, `timedOut: boolean`, and `failureReason: string | undefined`.
- [ ] The helper polls `journal.readinessInfo.breakpointRegistrationComplete` and returns early once all pending breakpoints are in a terminal state.

**Commit 2 — use it in bootstrap**
- [ ] Call `waitForBreakpointsInstalled` in `_initializeMainSessionInfrastructure` in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts) after the Python adapter connects.
- [ ] Propagate a structured error if the wait times out instead of silently continuing.

**Commit 3 — tests**
- [ ] Add timeout test: mock adapter never responds to `setBreakpoints`, verify bootstrap rejects with a structured error in [vscode/extension/test/dapperDebugAdapterFactory.test.ts](../../vscode/extension/test/dapperDebugAdapterFactory.test.ts).
- [ ] Add success test: mock adapter responds `verified`, verify bootstrap completes normally in [vscode/extension/test/dapperDebugAdapterFactory.test.ts](../../vscode/extension/test/dapperDebugAdapterFactory.test.ts).

---

### PR 5: Gate execution and replace unknown state

**Commit 1 — readiness guard in request handler**
- [ ] Add a `_checkReadiness()` helper in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts) that returns a structured error response if breakpoint registration is still in progress.
- [ ] Gate `continueRequest`, `nextRequest`, `stepInRequest`, and `stepOutRequest` behind `_checkReadiness()`.

**Commit 2 — structured failures for each failure mode**
- [ ] Return a distinct error message for each case: pending breakpoints, rejected breakpoints, and adapter-side failure in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts).

**Commit 3 — remove vague unknown state**
- [ ] Audit the `'unknown'` lifecycle paths in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts) and replace each one with the concrete state that should apply.
- [ ] Ensure `lastError` is always populated before assigning `'error'` state.

**Commit 4 — regression tests**
- [ ] Add a test proving that calling continue before breakpoints are ready returns a structured error in [vscode/extension/test/dapperDebugAdapterExtended.test.ts](../../vscode/extension/test/dapperDebugAdapterExtended.test.ts).
- [ ] Add a test proving the old vague unknown path now emits a concrete cause in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts).

---

### PR 6: Docs, wiring cleanup, and troubleshooting note

**Commit 1 — registration wiring**
- [ ] Ensure the enriched `dapper_session_info` surface is plumbed through [vscode/extension/src/extension.ts](../../vscode/extension/src/extension.ts) (`registerAgentTools`) and that package.json `contributes.languageModelTools` is updated.

**Commit 2 — roadmap and tool docs**
- [ ] Document the richer `dapper_session_info` output shape and readiness semantics in the agent-facing docs under [doc/](../../doc/).

**Commit 3 — troubleshooting note**
- [ ] Add a troubleshooting entry covering: breakpoint registration timeout, rejected breakpoints with no message, and adapter-side error state in the relevant getting-started or reference doc under [doc/](../../doc/).

## Checklist

### 1. Define session readiness state

- [ ] Add a session lifecycle model with explicit states such as initializing, waiting-for-breakpoints, ready, running, stopped, error, and unknown in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Track whether breakpoint registration has completed for the active session in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Record the last debugger-side transition that changed readiness in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Record the last debugger-side error or failure reason that pushed the session into an error or unknown state in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).

### 2. Expose breakpoint lifecycle status

- [ ] Extend the breakpoint verification model so each breakpoint can be reported as pending, verified, or rejected in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).
- [ ] Preserve the adapter message for rejected breakpoints in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts).
- [ ] Aggregate breakpoint status counts at the session level in [vscode/extension/src/agent/tools/breakpoints.ts](../../vscode/extension/src/agent/tools/breakpoints.ts) and [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).
- [ ] Make breakpoint registration completion visible to callers instead of inferring it from execution state in [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).

### 3. Add a richer session-status tool

- [ ] Enrich `dapper_session_info` in [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts) and keep it as the single session-inspection tool in [vscode/extension/src/agent/tools/index.ts](../../vscode/extension/src/agent/tools/index.ts).
- [ ] Return the current session lifecycle state from [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).
- [ ] Return whether breakpoint registration is complete from [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).
- [ ] Return counts and details for accepted, pending, and rejected breakpoints from [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).
- [ ] Return the last debugger-side error or transition reason from [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).
- [ ] Return a clear readyToContinue or equivalent flag from [vscode/extension/src/agent/tools/getSessionInfo.ts](../../vscode/extension/src/agent/tools/getSessionInfo.ts).

### 4. Implement an explicit ready wait

- [ ] Add a wait operation that completes only after breakpoint requests have been sent and the adapter response has been received in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts).
- [ ] Ensure the wait operation does not resolve until breakpoint verification records are in a terminal state or a timeout occurs in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts).
- [ ] Return a structured timeout or failure reason instead of a generic unknown state in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts).
- [ ] Use the wait operation in the main session bootstrap flow before allowing continuation in [vscode/extension/src/debugAdapter/mainSessionController.ts](../../vscode/extension/src/debugAdapter/mainSessionController.ts).

### 5. Gate execution on readiness

- [ ] Prevent continue or resume actions until the readiness gate passes in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts).
- [ ] Surface a specific error when readiness fails because breakpoints are pending, rejected, or unresponsive in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts).
- [ ] Surface a specific error when the adapter itself reports a failure in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts).
- [ ] Replace unknown-state behavior with a deterministic session status or failure mode in [vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts](../../vscode/extension/src/debugAdapter/dapperDebugSessionRequests.ts) and [vscode/extension/src/agent/stateJournal.ts](../../vscode/extension/src/agent/stateJournal.ts).

### 6. Cover the behavior with tests

- [ ] Add unit tests for session-status aggregation in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts) and [vscode/extension/test/dapperDebugAdapterExtended.test.ts](../../vscode/extension/test/dapperDebugAdapterExtended.test.ts).
- [ ] Add unit tests for breakpoint lifecycle transitions from pending to verified in [vscode/extension/test/breakpointsTool.test.ts](../../vscode/extension/test/breakpointsTool.test.ts).
- [ ] Add unit tests for breakpoint lifecycle transitions from pending to rejected in [vscode/extension/test/breakpointsTool.test.ts](../../vscode/extension/test/breakpointsTool.test.ts).
- [ ] Add a timeout test for waiting on breakpoint installation in [vscode/extension/test/dapperDebugAdapterFactory.test.ts](../../vscode/extension/test/dapperDebugAdapterFactory.test.ts) or [vscode/extension/test/dapperDebugAdapterExtended.test.ts](../../vscode/extension/test/dapperDebugAdapterExtended.test.ts).
- [ ] Add a regression test for the previous unknown-state path so it now reports a concrete cause in [vscode/extension/test/stateJournal.test.ts](../../vscode/extension/test/stateJournal.test.ts).

### 7. Document the new behavior

- [ ] Update tool documentation to describe the new status fields in the `dapper_session_info` registration and any agent-facing docs that mention it.
- [ ] Document the readiness semantics and breakpoint lifecycle states in the extension docs and roadmap docs under [doc/](../../doc/).
- [ ] Add a troubleshooting note for breakpoint registration failures and adapter-side errors in [doc/](../../doc/) and any relevant getting-started guide.

## Definition of Done

- [ ] A session status query shows whether breakpoint registration finished.
- [ ] A session status query shows which breakpoints were accepted, pending, or rejected.
- [ ] A session status query shows the last debugger-side error or transition that explains an unknown state.
- [ ] The debugger does not continue execution until breakpoint registration is actually complete.
- [ ] The previous vague unknown state is replaced by a concrete status or failure reason.