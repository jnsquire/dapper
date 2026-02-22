# Contributing

This page documents the contribution workflow, commit conventions, and code quality standards for dapper.

## Git Workflow Principles

1. **Make atomic commits** — each commit should address a single concern or implement one logical change.
2. **Prepare changes thoughtfully** — review your changes before committing.
3. **Write clear commit messages** — describe what and why, not just what.

## Commit Guidelines

**Good commit examples:**

```
Add TypedDict annotations to DAP command handlers

Replace dict[str, Any] parameters with specific TypedDict types
for better type safety and IDE support in DAP protocol handling.
```

```
Refactor handle_loaded_sources to reduce complexity

Extract helper functions for module source collection to eliminate
"too many branches" warning and improve maintainability.
```

**Avoid these patterns:**
- ❌ `Fix stuff` (too vague)
- ❌ `Update multiple files with various changes` (too broad)
- ❌ `WIP` or `temp` commits (unless clearly marked for rebasing)

## Preparing Changes for Commit

1. **Review your changes:**
   ```bash
   git status
   git diff
   ```

2. **Stage changes selectively:**
   ```bash
   # Stage specific files
   git add dapper/protocol/messages.py dapper/protocol/requests.py

   # Or stage interactively
   git add -p
   ```

3. **Verify staged changes:**
   ```bash
   git diff --staged
   ```

4. **Run tests before committing:**
   ```bash
   uv run pytest
   uv run ruff check .
   ```

5. **Commit with descriptive message:**
   ```bash
   git commit -m "Brief summary of changes

   Optional longer description explaining the motivation
   and implementation details if needed."
   ```

## Branching Strategy

- Use descriptive branch names: `feature/add-exception-handling`, `fix/memory-leak`, `refactor/command-handlers`
- Keep branches focused on single features or fixes
- Rebase or squash commits when merging to maintain clean history

## Before Submitting Changes

- [ ] All tests pass: `uv run pytest`
- [ ] Code passes linting: `uv run ruff check .`
- [ ] Changes are properly documented
- [ ] Commit messages are clear and descriptive
- [ ] Each commit represents a logical unit of work

## Contribution Workflow

1. **Create a feature branch from `main`:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes following the commit guidelines above.**

3. **Add tests for new functionality:**
   ```bash
   uv run pytest tests/test_your_feature.py
   ```

4. **Ensure all quality checks pass:**
   ```bash
   uv run pytest        # Run all tests
   uv run ruff check .  # Lint code
   ```

5. **Submit a pull request:**
   - Reference any related issues
   - Describe the changes and their motivation
   - Ensure CI passes

## Code Quality Standards

- Follow existing code style and patterns
- Add type annotations for new functions
- Update documentation for significant changes
- Maintain test coverage for new features
