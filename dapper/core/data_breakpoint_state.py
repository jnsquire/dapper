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

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    watch_meta: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_values_by_frame: dict[int, dict[str, object]] = field(default_factory=dict)
    global_values: dict[str, object] = field(default_factory=dict)

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
        self.watch_meta = {n: [] for n in self.watch_names}

        if metas:
            for name, meta in metas:
                if name in self.watch_meta:
                    self.watch_meta[name].append(meta)

    def clear(self) -> None:
        """Clear all data breakpoint state."""
        self.watch_names.clear()
        self.watch_meta.clear()
        self.last_values_by_frame.clear()
        self.global_values.clear()
        self.data_watches.clear()
        self.frame_watches.clear()

    def clear_value_snapshots(self) -> None:
        """Clear cached values but keep watch configuration."""
        self.last_values_by_frame.clear()
        self.global_values.clear()

    def get_meta_for_name(self, name: str) -> list[dict[str, Any]]:
        """Get the list of metadata dicts for a watched variable name."""
        return self.watch_meta.get(name, [])

    def has_watches(self) -> bool:
        """Check if any variables are being watched."""
        return bool(self.watch_names)

    def is_watching(self, name: str) -> bool:
        """Check if a specific variable is being watched."""
        return name in self.watch_names

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
                except Exception:  # pragma: no cover - defensive
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
