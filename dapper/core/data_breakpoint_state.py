"""
DataBreakpointState: Consolidated state management for data breakpoints (watchpoints).

This module provides a single coherent data structure for managing data breakpoint
state, replacing the scattered attributes previously spread across DebuggerBDB:
- data_watch_names -> watch_names
- data_watch_meta -> watch_meta
- last_values_by_frame (for change detection)
- global_values (for change detection)
- _data_watches (server-style)
- _frame_watches (server-style)
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.shared.value_conversion import evaluate_with_policy

if TYPE_CHECKING:
    from collections.abc import Mapping


def _normalize_access_type(access_type: Any) -> str:
    if not isinstance(access_type, str):
        return "write"
    lowered = access_type.strip().lower()
    if lowered == "read":
        return "read"
    if lowered in {"readwrite", "read_write", "read-write"}:
        return "readwrite"
    return "write"


@dataclass
class DataBreakpointState:
    """Consolidated state for data breakpoint (watchpoint) tracking.

    This class manages:
    1. Which variables are being watched (`watch_names`)
    2. Metadata for each watch (conditions, hit counts) (`watch_meta`)
    3. Previous values for change detection (`last_values_by_frame`, `global_values`)

    The server-style `data_watches` and `frame_watches` are optional and used
    by the adapter layer for DAP protocol compliance.

    Attributes:
        watch_names: Set of variable names being watched for changes.
        watch_meta: Mapping of variable name -> list of metadata dicts.
                   Each dict may contain 'condition', 'hitCondition', 'hit'.
        last_values_by_frame: Mapping of frame id -> {name: last_value}.
                             Used for per-frame change detection.
        global_values: Fallback mapping of name -> last_value for cases
                      where frame objects change between calls.
        data_watches: Server-style mapping of dataId -> watch metadata.
                     Used by adapter layer, optional for core debugger.
        frame_watches: Server-style mapping of frameId -> list of dataIds.
                      Used by adapter layer, optional for core debugger.
    """

    watch_names: set[str] = field(default_factory=set)
    read_watch_names: set[str] = field(default_factory=set)
    watch_meta: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_values_by_frame: dict[int, dict[str, object]] = field(default_factory=dict)
    global_values: dict[str, object] = field(default_factory=dict)
    watch_expressions: set[str] = field(default_factory=set)
    watch_expression_meta: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_expression_values_by_frame: dict[int, dict[str, object]] = field(default_factory=dict)
    global_expression_values: dict[str, object] = field(default_factory=dict)
    strict_expression_watch_policy: bool = False
    compiled_expression_cache: dict[str, Any] = field(default_factory=dict)

    # Server-style mappings (optional, used by adapter layer)
    data_watches: dict[str, dict[str, Any]] = field(default_factory=dict)
    frame_watches: dict[int, list[str]] = field(default_factory=dict)

    def register_watches(
        self,
        names: list[str],
        metas: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        """Replace the set of variable names to watch for changes.

        Args:
            names: List of variable names to watch.
            metas: Optional list of (name, metadata) tuples. Each metadata dict
                   may contain 'condition', 'hitCondition', etc.
        """
        self.watch_names = {n for n in names if isinstance(n, str) and n}
        self.read_watch_names = set()
        self.watch_meta = {n: [] for n in self.watch_names}

        if metas:
            names_with_meta: set[str] = set()
            write_names: set[str] = set()
            read_names: set[str] = set()
            for name, meta in metas:
                if name in self.watch_meta:
                    self.watch_meta[name].append(meta)
                    names_with_meta.add(name)
                    mode = _normalize_access_type(meta.get("accessType"))
                    if mode in {"write", "readwrite"}:
                        write_names.add(name)
                    if mode in {"read", "readwrite"}:
                        read_names.add(name)

            # Backward compatibility: if no metadata exists for a name,
            # preserve historical write-watch behavior.
            write_names.update(self.watch_names - names_with_meta)
            self.watch_names = write_names
            self.read_watch_names = read_names

    def clear(self) -> None:
        """Clear all data breakpoint state."""
        self.watch_names.clear()
        self.read_watch_names.clear()
        self.watch_meta.clear()
        self.last_values_by_frame.clear()
        self.global_values.clear()
        self.watch_expressions.clear()
        self.watch_expression_meta.clear()
        self.last_expression_values_by_frame.clear()
        self.global_expression_values.clear()
        self.compiled_expression_cache.clear()
        self.data_watches.clear()
        self.frame_watches.clear()

    def clear_value_snapshots(self) -> None:
        """Clear cached values but keep watch configuration."""
        self.last_values_by_frame.clear()
        self.global_values.clear()
        self.last_expression_values_by_frame.clear()
        self.global_expression_values.clear()

    def register_expression_watches(
        self,
        expressions: list[str],
        metas: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        """Replace the set of expressions to watch for value changes."""
        self.watch_expressions = {e for e in expressions if isinstance(e, str) and e.strip()}
        self.watch_expression_meta = {e: [] for e in self.watch_expressions}
        for expression in list(self.compiled_expression_cache):
            if expression not in self.watch_expressions:
                self.compiled_expression_cache.pop(expression, None)

        if metas:
            for expression, meta in metas:
                if expression in self.watch_expression_meta:
                    self.watch_expression_meta[expression].append(meta)

    def get_meta_for_name(self, name: str) -> list[dict[str, Any]]:
        """Get the list of metadata dicts for a watched variable name."""
        return self.watch_meta.get(name, [])

    def get_meta_for_expression(self, expression: str) -> list[dict[str, Any]]:
        """Get the list of metadata dicts for a watched expression."""
        return self.watch_expression_meta.get(expression, [])

    def has_watches(self) -> bool:
        """Check if any variables are being watched."""
        return bool(self.watch_names or self.watch_expressions)

    def is_watching(self, name: str) -> bool:
        """Check if a specific variable is being watched."""
        return name in self.watch_names

    def is_read_watching(self, name: str) -> bool:
        """Check if a specific variable is being watched for read-access."""
        return name in self.read_watch_names

    def check_for_changes(self, frame_id: int, current_locals: Mapping[str, Any]) -> list[str]:
        """Check for changes in watched variables and return all changed names.

        Args:
            frame_id: The id of the current frame (typically id(frame)).
            current_locals: The current local variables dict.

        Returns:
            A list of changed variable names (empty if no changes).
        """
        if not self.watch_names:
            return []

        changed: list[str] = []
        prior = self.last_values_by_frame.get(frame_id)

        for name in self.watch_names:
            if name not in current_locals:
                continue

            new_val = current_locals[name]
            old_val = None
            have_old = False

            # Check frame-specific snapshot first
            if prior is not None and name in prior:
                old_val = prior.get(name, object())
                have_old = True
            # Fall back to global snapshot
            elif name in self.global_values:
                old_val = self.global_values[name]
                have_old = True

            if have_old:
                try:
                    equal = new_val == old_val
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    equal = False
                if old_val is not new_val and not equal:
                    changed.append(name)

        return changed

    def update_snapshots(self, frame_id: int, current_locals: Mapping[str, Any]) -> None:
        """Update snapshots of watched variable values.

        Args:
            frame_id: The id of the current frame (typically id(frame)).
            current_locals: The current local variables dict.
        """
        if not self.watch_names:
            return

        # Snapshot current watched values per frame
        self.last_values_by_frame[frame_id] = {
            n: current_locals.get(n) for n in self.watch_names if n in current_locals
        }

        # Update global snapshot
        for n in self.watch_names:
            if n in current_locals:
                self.global_values[n] = current_locals[n]

    def check_expression_changes(self, frame_id: int, frame: Any) -> list[str]:
        """Check for changes in watched expressions and return changed expressions."""
        if not self.watch_expressions:
            return []

        changed: list[str] = []
        prior = self.last_expression_values_by_frame.get(frame_id)

        for expression in self.watch_expressions:
            try:
                new_val = self.evaluate_expression(expression, frame)
            except Exception:
                continue

            old_val = None
            have_old = False

            if prior is not None and expression in prior:
                old_val = prior.get(expression, object())
                have_old = True
            elif expression in self.global_expression_values:
                old_val = self.global_expression_values[expression]
                have_old = True

            if have_old:
                try:
                    equal = new_val == old_val
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    equal = False
                if old_val is not new_val and not equal:
                    changed.append(expression)

        return changed

    def update_expression_snapshots(self, frame_id: int, frame: Any) -> None:
        """Update snapshots of watched expression values."""
        if not self.watch_expressions:
            return

        current_values: dict[str, object] = {}
        for expression in self.watch_expressions:
            try:
                value = self.evaluate_expression(expression, frame)
            except Exception:
                continue
            current_values[expression] = value
            self.global_expression_values[expression] = value

        self.last_expression_values_by_frame[frame_id] = current_values

    def set_strict_expression_watch_policy(self, strict: bool) -> None:
        """Set whether expression watchpoints use strict policy checks."""
        self.strict_expression_watch_policy = bool(strict)

    def evaluate_expression(self, expression: str, frame: Any) -> object:
        """Evaluate a watched expression according to strict/permissive policy."""
        if self.strict_expression_watch_policy:
            return evaluate_with_policy(expression, frame, allow_builtins=True)

        code_obj = self.compiled_expression_cache.get(expression)
        if code_obj is None:
            code_obj = compile(expression, "<watch-expression>", "eval")
            self.compiled_expression_cache[expression] = code_obj

        globals_ctx = getattr(frame, "f_globals", {}) or {}
        locals_ctx = getattr(frame, "f_locals", {}) or {}
        return eval(cast("Any", code_obj), globals_ctx, locals_ctx)

    def has_data_breakpoint_for_name(
        self,
        name: str,
        frame_id: int | None = None,
    ) -> bool:
        """Check if a variable name has an associated data breakpoint.

        Used by variable presentation to indicate hasDataBreakpoint attribute.

        Args:
            name: The variable name to check.
            frame_id: Optional frame id for frame-specific checks.

        Returns:
            True if the variable has an associated data breakpoint.
        """
        # Check simple watch names
        if name in self.watch_names:
            return True

        # Check watch_meta
        if name in self.watch_meta:
            return True

        # Check server-style frame watches
        if frame_id is not None:
            data_ids = self.frame_watches.get(frame_id, [])
            for did in data_ids:
                if isinstance(did, str) and (f":var:{name}" in did or name in did):
                    return True

        return False


__all__ = ["DataBreakpointState"]
