# Agent-Focused Language Intelligence Plan

> **Goal:** Define the subset of Python language intelligence that is worth
> building or integrating when the target user is a tool-using agent rather
> than a human editing code interactively.

> **Scope:** This plan is not about matching a full Python IDE feature-for-
> feature. It is about identifying the semantic capabilities that materially
> improve agent correctness, edit precision, and bug-resolution workflow.

---

## Why this plan exists

For a human-focused extension, "language intelligence" often includes a large
amount of editor UX: completions, hover cards, highlighting, inline hints,
code lenses, snippets, and similar affordances.

For an agent, most of that is indirect or irrelevant. The useful question is
not "what makes Python pleasant to edit by hand?" It is:

- Can the agent find the right symbol or file reliably?
- Can the agent make a semantically correct change?
- Can the agent explain why the workspace is broken?
- Can the agent produce or narrow a repro without guessing?

This plan breaks the language-intelligence surface into three buckets:

- Minimum agent-grade language intelligence
- Nice-to-have language intelligence
- Low-value or unnecessary language intelligence for agents

---

## Current baseline in this repo

Verified against the current Dapper codebase and project configuration in
March 2026:

- [x] Dapper already has a debugger-first runtime foundation: launch/attach
  flows, interpreter preparation, launch history, process observability,
  and agent-facing paused-session tools.
- [x] The VS Code extension now contributes debugger/runtime LM tools plus
  early Python language-intelligence tools such as `dapper_python_environment`,
  `dapper_python_diagnostics`, and `dapper_python_typecheck`.
- [x] The extension still does not include a dedicated Python language
  server/client of its own, but it now does include tool-oriented
  diagnostics, symbol-navigation, and semantic edit surfaces via Ty/Ruff
  runners and VS Code language-feature providers.
- [x] The extension now has an internal environment snapshot API command,
      `dapper.api.getEnvironmentSnapshot`, that reports selected Python
      environment, Ty/Ruff resolution, and Ty/Ruff config-file discovery.
- [x] The extension now exposes a public `dapper_python_environment` LM tool
  for agent-facing Python/Ty/Ruff environment reporting.
- [x] The extension now exposes a public `dapper_python_diagnostics` LM tool
  that normalizes Ruff and Ty diagnostics into one shared schema and reports
  backend status explicitly.
- [x] The extension now exposes a public `dapper_python_symbol` LM tool for
  definition, references, implementations, and hover through the active VS
  Code semantic backend.
- [x] The extension now exposes a public `dapper_python_rename` LM tool for
  semantic rename with preview or apply modes through the active VS Code
  semantic backend.
- [x] The extension now exposes public `dapper_python_autofix` and
  `dapper_python_format` LM tools for Ruff-backed mechanical edits with
  preview or apply modes.
- [x] The extension now exposes a public `dapper_python_imports` LM tool for
  Ruff-backed import hygiene, including unused-import cleanup, import
  organization, and a combined mode.
- [x] The extension now has an internal Ruff runner service and API command,
  `dapper.api.runRuffCheck`, for structured Ruff check execution.
- [x] The extension now has an internal Ty runner service for structured Ty
  check execution.
- [x] The repo already uses Ruff as part of its development toolchain and has
  non-trivial Ruff configuration in `pyproject.toml`.
- [x] The repo already uses Pyright in development dependencies.
- [x] Ty is the baseline semantic backend for this roadmap.
- [x] Python plus Pylance remains the fallback semantic path during rollout.
- [x] Add Ty to the repository's declared tooling and integration baseline.
- [ ] Decide whether the first shippable milestone is read-only semantic
  intelligence or the full edit/validate loop.

Working interpretation:

- The main gap is not Python environment selection or debugger control.
- The main gap is the semantic read/edit layer that sits beside the debugger.
- The shortest path through this checklist is to ship read-path semantics
  first, then add mechanical quality actions, then add semantic mutations.

---

## Recommended order for working the checklist

The checklist below is comprehensive, but it should not be executed top to
bottom as one flat backlog. The practical order for Dapper is:

### Step 0 - Lock the backend decision

- [x] Use Ty as the first semantic backend target.
- [x] Keep Python plus Pylance as the fallback semantic path while Ty is being
  validated.
- [ ] Decide whether Ruff is always the first quality backend when available.
- [ ] Define fallback expectations up front: best-effort, warning-only, or
  hard dependency.

Exit criterion:

- The project can answer "what backend do we ship first, and what do we do
  when it is unavailable?" without ambiguity.

### Step 1 - Ship the environment snapshot first

- [x] Build the environment and executable-detection layer before any Ruff or
  Ty-specific runner work.
- [x] Reuse Dapper's existing interpreter/environment selection logic rather
  than inventing a second Python-resolution path for language tools.
- [x] Produce one structured snapshot that records interpreter, venv,
  workspace roots, executable provenance, and tool versions.

Exit criterion:

- Dapper can explain which Python, Ruff, and semantic backend it would use for
  the current workspace before trying to analyze anything.

Current progress:

- A shared environment snapshot now exists for Python environment selection,
  Ty/Ruff executable or module resolution, and Ty/Ruff config discovery.
- The snapshot is exposed publicly through `dapper_python_environment`.
- The remaining gap is broader project-model reporting beyond the current
  environment and tool-resolution slice.

### Step 2 - Prioritize the read path over the edit path

- [ ] Deliver syntax checking, diagnostics retrieval, import resolution, and
  symbol lookup before semantic rename or code actions.
- [ ] Treat this as the first user-visible milestone because it answers the
  core agent questions: what is this, where is it used, and what is
  broken?

Exit criterion:

- An agent can inspect a Python workspace semantically without relying on
  grep-heavy fallbacks.

### Step 3 - Add Ruff-backed mechanical actions next

- [x] Add formatting, safe autofix, and import cleanup after diagnostics are
  stable.
- [ ] Keep these actions explicitly separate from semantic refactors in both
  settings and result schemas.

Exit criterion:

- An agent can perform fast mechanical cleanup with bounded, explainable
  results.

### Step 4 - Add semantic mutations last

- [ ] Add definition, references, rename, and code actions only after the
  semantic backend has proven stable on representative repositories.
- [ ] Keep fallback behavior explicit when rename or code actions are not
  trustworthy for a given backend or workspace.

Exit criterion:

- Dapper can make structural edits semantically, not just diagnose problems.

### Step 5 - Use debugger data as the differentiator

- [ ] Treat the dynamic-static bridge as a deliberate later phase, not as a
  prerequisite for the first semantic release.
- [ ] Design every runtime-derived payload so agents can distinguish observed
  facts from static-analysis facts.

Exit criterion:

- Dapper adds value that Ruff, Ty, and Pylance cannot provide on their own.

---

## 1. Minimum agent-grade language intelligence

These capabilities directly affect whether an agent can operate safely and
productively in a Python workspace. Without them, the agent falls back to text
search, heuristics, and trial-and-error edits.

### 1.1 Syntax and parse validation

- [ ] Provide fast Python syntax checking for files and unsaved snippets.
- [ ] Return structured parse errors with file, line, column, and message.
- [ ] Support checking generated code before applying edits.

Why it matters:

- Prevents the agent from introducing obviously invalid code.
- Provides immediate feedback when a generated patch is malformed.
- Enables safer patch planning before a file is modified.

### 1.2 Import resolution and interpreter-aware module analysis

- [ ] Resolve imports against the active Python environment.
- [ ] Distinguish missing packages from missing source roots and typo-level
      import failures.
- [ ] Surface workspace source roots, interpreter paths, virtual environment
      location, and import search path.
- [ ] Detect unresolved imports and shadowed imports.
- [ ] Account for type stubs (`types-*` packages), typeshed, and `py.typed`
      inline typing when evaluating type coverage.
- [ ] Help agents understand why type information is missing for a dependency:
      no stubs available, untyped library, or misconfigured search path.

Why it matters:

- Python code is only understandable in the context of the active interpreter.
- Many "bugs" are environment or import-graph problems rather than runtime
  logic problems.
- Agents need to tell the difference between a bad edit and a bad environment.
- Many popular libraries have no inline types and depend entirely on stubs;
  real-world type analysis quality is dominated by stub and typeshed coverage.

### 1.3 Structured diagnostics

- [x] Collect syntax, import, type, and selected semantic diagnostics for the
      workspace and for individual files.
- [ ] Group diagnostics by severity and file.
- [x] Preserve machine-actionable metadata where available.
- [x] Expose diagnostics in a way that an agent can consume without scraping
      UI text.

Why it matters:

- This is the main feedback loop that tells the agent whether an edit made the
  codebase healthier or worse.
- Diagnostics often localize the problem faster than executing the code.
- Clean bug-resolution workflows require a reliable "what is broken now?"
  answer.

### 1.4 Symbol navigation and cross-reference lookup

- [x] Support go to definition for modules, classes, functions, methods,
      variables, and imported names.
- [x] Support find references / usages.
- [ ] Support workspace symbol search.
- [x] Support implementation lookup where the language stack can infer it.
- [x] Preserve file and location identity in results.

Why it matters:

- This is the difference between semantic editing and grep-based editing.
- Most non-trivial fixes require understanding where a symbol is defined and
  what else depends on it.
- Refactors and bug investigations both depend on accurate symbol routing.

### 1.5 Type, signature, and doc inspection

- [ ] Return inferred or declared type information for expressions and symbols.
- [ ] Return call signatures with parameter names and defaults.
- [ ] Return docstrings or symbol documentation.
- [ ] Return base-class and override relationships when available.

Why it matters:

- Agents need semantic shape more than UI hover text.
- The ability to inspect types and signatures reduces bad API usage.
- Docstrings help the agent choose among similarly-named helpers without
  reading every implementation body.

### 1.6 Safe refactoring and code actions

- [x] Support semantic rename.
- [x] Support import organization and unused-import cleanup.
- [ ] Support selected safe code actions such as add missing imports,
      convert import forms, or apply fix-all where the language stack offers
      them.
- [x] Allow preview or dry-run of refactor edits before applying them.

Why it matters:

- Agents frequently need structural edits, not just local line patches.
- Semantic rename is much safer than find-and-replace.
- Quick fixes turn diagnostics into actionable remediations.

### 1.7 Project model and workspace semantics

- [ ] Discover Python workspace roots and user files.
- [x] Detect config sources such as `pyproject.toml`, `setup.cfg`,
      `pytest.ini`, `tox.ini`, and notebook metadata where relevant.
- [x] Identify test roots, source roots, and package boundaries.
- [ ] Surface the active Python environment and available environments.

Why it matters:

- Agents need a correct model of the workspace before editing it.
- Many wrong edits come from misunderstanding package boundaries or config
  ownership.
- Bug reports are much easier to resolve when the project model is explicit.

### 1.8 Ruff-aligned quality layer

- [x] Integrate Ruff lint diagnostics as a first-class agent feedback source.
- [x] Integrate Ruff autofix for safe, mechanical remediations.
- [x] Integrate Ruff formatting where the workspace chooses Ruff as the
      formatter.
- [x] Integrate Ruff import organization and unused-import cleanup as explicit
      agent actions.
- [x] Surface Ruff rule identifiers and fixability metadata in tool results.

Why it matters:

- Ruff covers a large and valuable part of the agent feedback loop: syntax-
  adjacent issues, code quality diagnostics, import hygiene, style
  normalization, and many safe autofixes.
- Ruff is fast enough to support tight edit-validate cycles, which matters for
  agent iteration.
- Ruff can replace a broad set of quality tools with one consistent interface,
  which simplifies both extension integration and agent prompting.

Important limitation:

- Ruff does not replace symbol navigation, cross-reference lookup, semantic
  rename, rich type analysis, or doc/signature inspection.
- Treat Ruff as a major part of the quality-and-remediation layer, not as the
  entire language-intelligence stack.

### 1.9 Ty-aligned semantic layer

- [x] Evaluate Ty as the primary type-checking and language-server backend.
- [x] Integrate Ty diagnostics as a first-class agent feedback source.
- [ ] Integrate Ty-backed definition, references, rename, completions,
      code actions, and related language-server capabilities where available.
- [x] Expose Ty type information and contextual diagnostics through agent-
      friendly tool payloads.
  - [x] Define a shared `typeInfo` schema for declared type, inferred type,
    symbol kind, and source attribution.
  - [x] Define a shared `diagnosticContext` schema for Ty explanations,
    notes, related locations, and rule/code metadata.
  - [x] Extend `dapper_python_typecheck` to return Ty-enriched diagnostics
    without requiring UI-text scraping.
  - [x] Extend `dapper_python_symbol` to return type, signature, and
    documentation fields where the active semantic backend provides them.
  - [x] Add output-budget controls for Ty-enriched payloads: truncation,
    pagination, and explicit partial-result markers.
  - [x] Add unit and integration coverage for Ty type payloads, contextual
    diagnostics, and backend-failure semantics.
- [x] Account for Ty's current beta status in dependency and rollout planning.

Why it matters:

- Ty is explicitly positioned as both a Python type checker and a language
  server, which makes it relevant to the semantic half of the checklist that
  Ruff does not cover.
- Ty's diagnostic system appears designed to provide rich, contextual error
  messages, which is especially useful for agent reasoning and bug
  explanation.
- If Ty's language-server capabilities are mature enough in practice, it can
  cover a substantial share of the minimum agent-grade semantic surface:
  diagnostics, navigation, rename, completions, code actions, and type-driven
  analysis.

Important limitation:

- Ty is still in beta and does not yet present a stable API or fully mature
  feature envelope.
- It should be treated as a promising semantic backend, but one that needs
  careful validation against real Python repositories and agent workflows.

### 1.10 Dynamic-static analysis bridge

- [ ] Define how runtime type information observed during debug sessions can
      supplement static type analysis, especially for untyped or `Any`-typed
      call sites that Ty or Pylance cannot resolve.
- [ ] Expose runtime call graphs from observed debug sessions as a precise
      complement to static call-hierarchy analysis.
- [ ] Allow runtime import paths (what actually got imported, from where) to
      validate or contradict static import resolution.
- [ ] Surface runtime variable types, shapes, and values alongside static
      type annotations when both are available for a symbol.
- [ ] Design the bridge so that static analysis is the default path and
      runtime observations are additive enrichment, not a dependency.

Why it matters:

- Dapper is a debugger. No other tool in this space has access to both static
  analysis and live runtime state. This is a differentiating opportunity.
- Python's dynamic nature means static analysis is weakest exactly where
  runtime observation is strongest: untyped libraries, dynamic dispatch,
  metaprogramming, and data-dependent control flow.
- Debug sessions already produce observed call stacks, resolved import paths,
  and concrete types. Surfacing these to the agent turns debugging artifacts
  into semantic intelligence.
- This capability has no pure-static equivalent and cannot be replicated by
  Ruff, Ty, or Pylance alone.

Important limitation:

- Runtime observations are path-specific and may not generalize. They should
  be treated as high-confidence evidence for the observed execution, not
  universal facts about the codebase.
- The bridge needs clear labeling so agents can distinguish static-analysis
  results from runtime-observed results.

---

## 2. Nice-to-have language intelligence

These features can improve agent efficiency or reduce ambiguity, but they are
not strictly required for clean agent workflows.

### 2.1 Completion-style candidate generation

- [ ] Expose completion candidates for module members, object attributes, and
      configuration keys where the backing language service already supports
      this cheaply.

Why it helps:

- Useful when the agent is choosing among unfamiliar APIs.
- Can reduce speculative symbol-name guessing.

Why it is not core:

- Agents can often recover from missing completions via symbol lookup, docs,
  and definitions.

### 2.2 Signature-help style call assistance

- [ ] Return overload-aware call signatures for a specific call site.
- [ ] Highlight active parameter position when available.

Why it helps:

- Useful in edit-time reasoning about function calls.

Why it is not core:

- Much of the value overlaps with general signature inspection.

### 2.3 Hover-equivalent symbol summaries

- [ ] Provide compact symbol summaries that combine type, docs, and source
      location.

Why it helps:

- Good for quick agent decisions without multiple tool calls.

Why it is not core:

- The value comes from the underlying metadata, not the hover UI concept.

### 2.4 Call hierarchy and richer relationship graphs

- [ ] Support incoming/outgoing call hierarchy for Python symbols.
- [ ] Support class hierarchy browsing.

Why it helps:

- Speeds up impact analysis in larger codebases.
- Useful for architectural or bug-propagation analysis.

Why it is not core:

- It is an accelerator, not a prerequisite, if definitions and references are
  already available.

### 2.5 Notebook-aware semantic support

- [ ] Preserve semantic understanding across notebooks and Python files.
- [ ] Route definitions and diagnostics across notebook cell boundaries where
      possible.

Why it helps:

- Important for agent workflows in data-science-heavy repositories.

Why it is not core:

- Many software repositories do not need notebook intelligence at all.

---

## 3. Low-value or unnecessary language intelligence for agents

These features mainly serve human editor ergonomics. They may still be worth
shipping for interactive users, but they are not strong requirements for an
agent-first extension.

### 3.1 Mostly human-facing editor presentation

- [ ] Semantic token coloring
- [ ] Inlay hints as visual decoration
- [ ] Breadcrumbs
- [ ] Folding regions
- [ ] bracket-pair or indent guide presentation

Why low value:

- Agents do not consume the rendered editor surface.
- The underlying structure may matter, but the visual affordance itself does
  not.

### 3.2 Snippet and typing accelerators

- [ ] Snippet packs
- [ ] auto-closing / paired typing behaviors
- [ ] editor micro-productivity helpers

Why low value:

- These optimize manual typing throughput, not semantic reasoning.

### 3.3 UI-only lenses and decorations

- [ ] CodeLens counts
- [ ] rich gutter decorations unrelated to diagnostics
- [ ] outline presentation polish

Why low value:

- Agents need the underlying data, not the UI treatment.

---

## 4. Dapper-specific implications

The current Dapper VS Code extension is debugger-first. It already provides a
substantial runtime and debugging foundation:

- debug launch and attach flows
- interpreter/environment preparation for debugger execution
- launch configuration wizard and run/debug commands
- process and launch observability
- agent-facing debug tools for paused-session inspection and control

That is a strong base for runtime diagnosis, but it does not yet provide the
minimum language-intelligence layer described above.

Implication:

- Dapper does not need to become a full human-facing Python IDE to become
  agent-complete.
- Dapper does need a semantic backend and tool surface for the minimum set in
  Section 1.

Additional implication from the current repo state:

- The first tranche of work should plug into the existing environment and
  launch model, not bypass it.
- The first tranche should be read-oriented and schema-oriented, because that
  delivers agent value without immediately taking on the correctness risk of
  semantic mutation.

---

## 5. Recommended implementation strategy

Before choosing a language-stack strategy, separate two concerns:

- semantic navigation and analysis
- quality diagnostics, formatting, and autofix

Ruff is especially strong in the second category.
Ty appears strong in the first category and overlaps with part of the
diagnostics layer.

### Option A — Integrate an existing Python language stack

- [ ] Depend on Ty as the primary language-intelligence backend.
- [ ] Preserve compatibility with the Python extension and Pylance as the
  fallback semantic path.
- [ ] Depend on Ruff for linting, formatting, import hygiene, and safe
  autofix where the workspace uses it.
- [ ] Expose agent-friendly command and tool wrappers over that language stack.
- [ ] Keep Dapper focused on debugging, runtime state, and bug-resolution UX.

Pros:

- Fastest path to strong semantics.
- Ty + Ruff provides a potentially cohesive Astral-based toolchain.
- Fastest path to strong semantics plus high-quality edit/validate loops.
- Avoids rebuilding a Python language server stack.
- Leverages a mature diagnostic and indexing engine.
- Lets Ruff handle a large share of mechanical cleanup and quality feedback.

Cons:

- Requires explicit integration boundaries and dependency assumptions.
- Agent tool quality becomes partially dependent on external extension quality.
- Ty specifically adds beta-lifecycle risk until its stability and coverage are
  proven on target repositories.

### Option B — Build a smaller agent-only semantics layer

- [ ] Implement only the minimum set from Section 1.
- [ ] Use Ruff as the default diagnostics / formatting / autofix backend where
  possible.
- [ ] Consider Ty as the default semantic backend before building custom
  navigation and type-analysis services.
- [ ] Avoid human-IDE features that do not contribute to agent workflows.
- [ ] Keep the surface strongly tool-oriented rather than UI-oriented.

Pros:

- Smaller than building a full Python IDE.
- Ruff reduces the amount of custom diagnostics and formatting infrastructure
  Dapper would need to own.
- Ty may reduce the amount of custom semantic infrastructure Dapper would need
  to own.
- More control over agent-oriented behavior and payload shape.

Cons:

- Still a meaningful language-tools project.
- Ruff still leaves symbol, type, reference, and documentation gaps.
- Ty's beta status means fallback planning is still required.
- Hard to match the correctness and coverage of a mature language stack.

### Recommendation

- [x] Prefer Option A unless there is a strong product reason to avoid
      depending on external Python language infrastructure.
- [x] Treat Ruff + Ty as the first toolchain to integrate.
- [x] Keep a fallback path to Python + Pylance until Ty's stability and
      feature coverage are validated for Dapper's target repositories.
- [ ] Treat Dapper's core value as debugger/runtime depth, not generic Python
      editor parity.

Decision record:

- Ty is the baseline semantic backend for the first implementation passes in
  this plan.
- Ruff remains the intended quality backend when available.
- Python plus Pylance is retained as the semantic fallback until Ty proves
  stable enough on representative Dapper target repositories.

---

## 6. Ruff + Ty integration checklist for Dapper

This section turns the strategy above into concrete extension and agent-tooling
work.

### 6.1 Workspace and environment detection

- [x] Detect whether Ruff is available in the active workspace environment.
- [x] Detect whether Ty is available in the active workspace environment.
- [x] Detect whether the user has configured Ruff or Ty in `pyproject.toml` or
  related config files.
- [x] Distinguish between bundled/global tool availability and workspace-local
  tool availability.
- [x] Record the active interpreter, tool executable path, and tool version in
  a structured environment snapshot.

Acceptance signal:

- Dapper can explain exactly which Ruff and Ty executables it intends to use,
  and why.

### 6.2 Ruff command execution surface

- [x] Add an internal Ruff runner service in the extension.
- [x] Support file-scoped Ruff checks.
- [x] Support workspace-scoped Ruff checks.
- [x] Support Ruff autofix for selected files.
- [x] Support Ruff format for selected files.
- [x] Support Ruff import cleanup / organize-import workflows where supported
  by the active configuration.
- [ ] Capture stdout, stderr, exit code, timing, and invoked arguments in a
  structured result object.

Acceptance signal:

- Dapper can run Ruff repeatably and expose results without shell-text
  scraping.

### 6.3 Ty command and language-service surface

- [x] Add an internal Ty runner or integration layer in the extension.
- [x] Support file-scoped Ty checks.
- [x] Support workspace-scoped Ty checks.
- [x] Support structured Ty diagnostics retrieval.
- [ ] Evaluate whether Dapper should integrate Ty through its VS Code language
  server extension, direct CLI usage, or both.
- [x] Prefer language-server-backed features for navigation, rename, and code
  actions when available.
- [ ] Capture stdout, stderr, exit code, timing, and invoked arguments in a
  structured result object for CLI-backed flows.

Acceptance signal:

- Dapper can retrieve Ty-backed semantic diagnostics and can route semantic
  editor actions through a stable integration path.
- When Ty is unavailable or unsuitable, Dapper can fall back to Python plus
  Pylance without changing the higher-level agent workflow shape.

### 6.4 Agent tool surface

- [x] Add a `python_diagnostics`-style tool that merges Ruff and Ty results
  while preserving source attribution. Initial public slice is Ruff-backed and
  reports Ty backend status separately until Ty diagnostics are integrated.
- [x] Add a `python_format`-style tool that can invoke Ruff formatting.
- [x] Add a `python_autofix`-style tool for Ruff safe fixes.
- [x] Add a `python_imports`-style tool for unused-import cleanup, import
  organization, and combined import hygiene workflows.
- [x] Add a `python_typecheck`-style tool for Ty checks.
- [x] Add a `python_symbol`-style tool family for definition, references,
  rename, and symbol inspection through Ty or the fallback semantic
  backend.
- [x] Add a `python_environment`-style tool for interpreter, package, and tool
  version reporting.
- [x] Add a `python_project_model`-style tool for source roots, test roots,
  config files, and package-boundary reporting.
- [ ] Include output-size management in every tool: support pagination,
      truncation, file-scope filtering, and priority ordering so that
      large-workspace results fit within agent token budgets.
- [x] Provide contextual diagnostic explanation where possible, not only raw
      diagnostic text. Help agents understand what a diagnostic means and why
      it was raised, especially for type errors with non-obvious causes.
- [x] Extend `python_typecheck` results with shared `typeInfo`,
  `diagnosticContext`, and completion-status fields.
- [x] Extend `python_symbol` inspection results with shared `typeInfo`,
  signature, and documentation fields.

Acceptance signal:

- An agent can perform the full edit-validate loop through structured tools
  rather than terminal commands and grep fallbacks.
- Tool responses remain useful and bounded even in workspaces with hundreds
  of diagnostics.
- Type, signature, documentation, and contextual Ty error payloads are
  returned through stable schemas rather than provider-specific hover text.

### 6.5 Result schema and conflict handling

- [x] Define a shared diagnostics schema that records source tool (`ruff`,
  `ty`, or fallback provider), severity, rule/code, fixability, location,
  and explanatory text.
- [x] Define a shared action-result schema for format, autofix, and rename
  operations.
- [x] Define a shared semantic payload schema for `typeInfo`, signatures,
      documentation, `diagnosticContext`, and output-budget metadata.
- [ ] Decide how to merge overlapping Ruff and Ty diagnostics without hiding
  useful distinctions.
- [x] Preserve enough metadata for the agent to decide whether an issue is
  style-only, semantic, or type-driven.
- [ ] Define how unsaved or in-flight content is handled: whether Ruff and Ty
  can analyze buffer content via stdin or temp files, or whether a
  save-analyze-revert workflow is required.
- [ ] Clarify the interaction between buffer-level analysis and the language-
  server protocol's `textDocument/didChange` model.
- [ ] Support pre-edit validation: the agent should be able to check proposed
  code against the analysis backends before writing it to disk.

Acceptance signal:

- Diagnostic consumers do not need tool-specific parsing logic for common
  workflows.
- An agent can validate a proposed edit before applying it, without requiring
  a file save round-trip.
- Type-oriented inspection and contextual diagnostics share one payload shape
  across `python_typecheck` and `python_symbol`.

### 6.6 Fallback and compatibility policy

- [ ] Define the fallback path when Ruff is unavailable.
- [ ] Define the fallback path when Ty is unavailable.
- [ ] Define the fallback path when Ty is installed but not sufficiently stable
  for a repository's language features or dependency patterns.
- [x] Preserve compatibility with Python + Pylance as a semantic fallback while
      Ty rollout is ongoing.
- [ ] Decide whether Dapper should offer soft warnings, hard requirements, or
  best-effort behavior for missing tools.
- [ ] Define a version-pinning or compatibility-range policy for Ruff and Ty.
  Decide whether Dapper pins supported versions, accepts semver ranges, or
  tests against latest-at-ship-time.
- [ ] Add a CI gate that validates Dapper's integration against the latest
  Ruff and Ty releases before each Dapper release.
- [ ] Define detection and upgrade guidance when a breaking change in Ruff or
  Ty CLI flags, diagnostic output, or LSP behavior affects Dapper.
- [ ] Define error-recovery and partial-result semantics: distinguish "no
  issues found" from "analysis failed" from "analysis timed out and
  results are incomplete."
- [ ] Handle tool misbehavior (crashes, non-zero exit on valid input,
  nonsensical output) with explicit error reporting rather than silent
  omission of results.
- [ ] Tag every tool result with a completion status (complete, partial,
  failed, timed-out) so agents never mistake a backend failure for a
  clean workspace.

Acceptance signal:

- Dapper can degrade gracefully instead of failing the entire agent workflow
  when one backend is missing or unsuitable.
- Agents can always tell whether a result reflects a complete analysis or a
  partial/failed one.

### 6.7 Configuration and user control

- [ ] Add extension settings to control preferred semantic backend (`ty`,
  `pylance`, `auto`).
- [ ] Add extension settings to control preferred quality backend (`ruff`,
  `none`, `auto`).
- [ ] Add settings for fix mode preferences: diagnostics only, safe autofix,
  or explicit user confirmation.
- [ ] Add settings or heuristics for workspace trust, large-workspace limits,
  and background analysis behavior.
- [ ] Document executable resolution order and environment assumptions.

Acceptance signal:

- Backend choice and automation level are explicit, debuggable, and default to
  the Ty-first policy described above.

### 6.8 Validation matrix

- [ ] Validate on a small typed project.
- [ ] Validate on a partially typed legacy project.
- [ ] Validate on a monorepo or multi-root layout.
- [ ] Validate on a notebook-heavy or mixed tooling repository if that user
  segment matters.
- [ ] Compare Ty-backed navigation and diagnostics against the fallback
  provider on representative repositories.
- [ ] Check agent workflows for latency, determinism, and diagnostic quality.

Acceptance signal:

- Backend selection is based on observed agent outcomes, not only feature
  claims.

### 6.9 Performance and latency model

- [ ] Define target response-time envelopes for each tool category:
  syntax check, diagnostics retrieval, navigation, format, autofix.
- [ ] Determine whether incremental or cached analysis is assumed or required
  for acceptable agent iteration speed.
- [ ] Plan for first-analysis cold start: Ty and Ruff may need to index a
  large workspace before returning useful results. Define what happens
  during that window.
- [ ] Measure and document observed latencies on representative repositories
  for each backend and tool.

Acceptance signal:

- Agent edit-validate cycles meet a documented latency threshold on
  representative workspaces.
- Cold-start behavior is explicit and does not silently degrade tool quality.

### 6.10 Concurrency and parallel tool invocations

- [ ] Determine whether Ruff and Ty backends handle concurrent requests safely.
- [ ] Define whether tool handlers need serialization, locking, or
  request-queuing when multiple tools are invoked in parallel.
- [ ] Define the interaction model when one tool mutates a file (autofix,
  format) while another reads diagnostics concurrently.
- [ ] Ensure that file-mutating tools return or invalidate stale cached
  analysis results.

Acceptance signal:

- Parallel tool invocations do not produce corrupt, stale, or
  nondeterministic results.

### 6.11 Remote and container development

- [ ] Scope whether Remote-SSH, Dev Containers, WSL, and similar remote
  development scenarios are in scope.
- [ ] If in scope: define how executable detection (Ruff, Ty, Python) works
  when the interpreter and tools live on a different machine from the
  VS Code UI.
- [ ] If in scope: define how runner services (6.2, 6.3) invoke tools on
  the remote host rather than the local machine.
- [ ] If out of scope: document the limitation explicitly.

Acceptance signal:

- Remote development is either supported with tested paths or explicitly
  documented as unsupported.

### 6.12 Testing strategy for the integration layer

- [x] Add unit tests for tool handlers with mocked Ruff and Ty output.
- [ ] Add integration tests against pinned Ruff and Ty versions.
- [ ] Add regression tests that detect when a Ruff or Ty version bump changes
  diagnostic output, CLI flags, or result schema.
- [ ] Ensure the existing extension test suite does not become tightly coupled
  to language-backend behavior.
- [ ] Include tests for error-recovery paths: backend crashes, timeouts,
  partial output, and unavailable executables.

Acceptance signal:

- Integration failures are caught by CI before reaching users.
- Backend version bumps produce actionable test failures, not silent behavior
  changes.

### 6.13 Rollout phases

#### Phase A — Quality layer

- [x] Ship Ruff detection, diagnostics, formatting, and autofix.
- [x] Expose Ruff-backed agent tools first.
- [x] Use this phase to harden environment and executable resolution.

#### Phase B — Semantic diagnostics

- [x] Ship Ty detection and structured type-check diagnostics.
- [ ] Compare diagnostics quality and stability against fallback providers.
- [ ] Keep navigation and refactoring behind a validation gate until proven.

Goal of this phase:

- Establish Ty as the default semantic read-path backend for supported
  workspaces.

#### Phase C — Semantic editor actions

- [ ] Ship Ty-backed definition, references, rename, and code actions where the
  integration is reliable.
- [ ] Preserve a fallback path for repositories that do not behave well under
  Ty.

#### Phase D — Unified bug-resolution loop

- [ ] Combine Ruff diagnostics, Ty diagnostics, test failures, environment
  state, and Dapper runtime state into one repro-oriented workflow.
- [ ] Integrate the dynamic-static analysis bridge (Section 1.10): enrich
  static diagnostics with runtime type observations, observed call paths,
  and resolved import paths from debug sessions where available.
- [ ] Make the output suitable for both agent consumption and human bug-report
  triage.

---

## 7. Suggested phased roadmap

### Phase 1 — Agent-grade semantic read path

- [ ] Syntax checking for files and snippets
- [ ] Import resolution and environment-aware module discovery
- [x] File/workspace diagnostics retrieval
- [x] Ruff diagnostics retrieval with rule and fixability metadata
- [x] Ty diagnostics retrieval with structured type and semantic context
- [x] Definition and reference lookup
- [ ] Type/signature/doc inspection

Acceptance signal:

- An agent can answer "what is this symbol, where is it used, and what is
  broken in this workspace?" without relying on grep-heavy fallback flows.
- Type and signature inspection returns structured fields, and contextual Ty
  diagnostics do not require hover-text or CLI-text scraping.

### Phase 2 — Agent-grade semantic edit path

- [x] Semantic rename
- [x] Ruff autofix and formatting execution
- [ ] Ty-backed rename, code actions, and semantic edit support
- [ ] Organize imports and selected safe quick fixes
- [ ] Workspace-aware refactor previews
- [x] Configuration-aware project model reporting

Acceptance signal:

- An agent can make targeted structural edits and validate them semantically.

### Phase 3 — Bug-resolution workflow support

- [x] Repro-oriented environment snapshot
- [ ] Installed-package and interpreter reporting
- [ ] Config source discovery for Python, test, and quality tools
- [ ] Joined view of diagnostics, failing tests, and debug launch context

Acceptance signal:

- A bug report can be turned into a reproducible, diagnosable workspace state
  with minimal manual reconstruction.

### Phase 4 — Optional accelerators

- [ ] Completion-style candidate lookup
- [ ] call hierarchy
- [ ] notebook semantic support where product needs justify it

Acceptance signal:

- Agent workflows become faster, but not newly possible.

---

## 8. Decision rule for future features

Before adding a new language-intelligence feature, ask:

1. Does it help an agent find the right code more reliably?
2. Does it help an agent make a more semantically correct edit?
3. Does it help an agent explain or localize a bug faster?
4. Does it improve reproducibility or bug-report resolution?
5. Is the integration cost proportionate to the agent-workflow improvement?

If the answer to questions 1–4 is no, it is probably not part of the minimum
agent-grade language-intelligence surface. If a feature passes 1–4 but fails
5, it should be deferred until the cost-benefit ratio improves (e.g., because
a backend matures or a simpler integration path becomes available).

---

## 9. Summary

For agent development, the important part of language intelligence is the
semantic backend, not the editor chrome.

The minimum useful set is:

- syntax validation
- import and environment resolution
- structured diagnostics
- symbol navigation and cross-references
- type, signature, and doc inspection
- safe semantic refactoring
- project-model awareness
- dynamic-static analysis bridge (runtime observations enriching static
  analysis)

Ruff is a strong fit for:

- diagnostics
- formatting
- import cleanup
- unused-code cleanup
- safe mechanical autofix

Ty is a strong fit for:

- type checking
- rich contextual diagnostics
- language-server-backed navigation
- rename and code actions
- completions and related semantic editor services

Ruff is not, by itself, a replacement for:

- symbol navigation
- reference lookup
- semantic rename
- rich type analysis
- signature and doc inspection

Ty plus Ruff is close to a full agent-grade language-intelligence stack,
provided Ty's beta-state risks are acceptable and its real-world coverage holds
up on the kinds of repositories Dapper cares about.

Everything else should be justified against agent correctness or bug-resolution
value, not against traditional IDE expectations.
