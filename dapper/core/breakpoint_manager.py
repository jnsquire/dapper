# ruff: noqa: I001
"""BreakpointManager: Centralized breakpoint state management.

This module provides unified management for all breakpoint types:
1. Line breakpoints with metadata (conditions, hit counts, log messages)
2. Function breakpoints with metadata
3. Custom breakpoints (programmatically set)
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from dapper.core.breakpoint_resolver import BreakpointMeta


# Re-export BreakpointMeta as LineBreakpointMeta for backward compatibility
LineBreakpointMeta = BreakpointMeta


@dataclass
class BreakpointManager:
    """Manages all breakpoint state for the debugger.

    This class consolidates breakpoint-related state that was previously
    scattered in DebuggerBDB:
    - breakpoint_meta: line breakpoint metadata (condition, hit, log)
    - function_breakpoints: list of function names to break on
    - function_breakpoint_meta: metadata for function breakpoints
    - custom_breakpoints: programmatically set breakpoints

    Attributes:
        line_meta: Mapping of (path, line) -> metadata dict.
        function_names: List of function names to break on.
        function_meta: Mapping of function name -> metadata dict.
        custom: Mapping of filename -> {line -> condition}.

    """

    line_meta: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    _line_meta_by_path: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    function_names: list[str] = field(default_factory=list)
    function_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom: dict[str, dict[int, str | None]] = field(default_factory=dict)

    # --- Line Breakpoint Methods ---

    def record_line_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None = None,
        hit_condition: str | None = None,
        log_message: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Record metadata for a line breakpoint.

        Args:
            path: The file path.
            line: The line number.
            condition: Optional condition expression.
            hit_condition: Optional hit count condition.
            log_message: Optional log message (makes this a logpoint).
            **kwargs: Additional metadata (e.g. verified, message, id).

        """
        key = (path, int(line))
        meta = self.line_meta.get(key, {})
        meta.setdefault("hit", 0)
        meta["condition"] = condition
        meta["hitCondition"] = hit_condition
        meta["logMessage"] = log_message
        meta.update(kwargs)
        self.line_meta[key] = meta
        if path not in self._line_meta_by_path:
            self._line_meta_by_path[path] = {}
        self._line_meta_by_path[path][int(line)] = meta

    def get_line_meta(self, path: str, line: int) -> dict[str, Any] | None:
        """Get metadata for a line breakpoint.

        Args:
            path: The file path.
            line: The line number.

        Returns:
            The metadata dict, or None if not found.

        """
        normalized_line = int(line)
        path_meta = self._line_meta_by_path.get(path)
        if path_meta is not None and normalized_line in path_meta:
            return path_meta[normalized_line]

        meta = self.line_meta.get((path, normalized_line))
        if meta is not None:
            if path not in self._line_meta_by_path:
                self._line_meta_by_path[path] = {}
            self._line_meta_by_path[path][normalized_line] = meta
        return meta

    def clear_line_meta_for_file(self, path: str) -> None:
        """Clear all line breakpoint metadata for a file.

        Args:
            path: The file path to clear metadata for.

        """
        path_meta = self._line_meta_by_path.pop(path, None)
        if path_meta is not None:
            for line in path_meta:
                self.line_meta.pop((path, line), None)
            return

        to_del = [k for k in self.line_meta if k[0] == path]
        for key in to_del:
            self.line_meta.pop(key, None)

    def increment_hit_count(self, path: str, line: int) -> int:
        """Increment and return the hit count for a breakpoint.

        Args:
            path: The file path.
            line: The line number.

        Returns:
            The new hit count.

        """
        normalized_line = int(line)
        meta = self.get_line_meta(path, normalized_line)
        if meta is None:
            return 0
        meta["hit"] = meta.get("hit", 0) + 1
        return meta["hit"]

    # --- Function Breakpoint Methods ---

    def set_function_breakpoints(
        self,
        names: list[str],
        metas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Set function breakpoints, replacing any existing ones.

        Args:
            names: List of function names to break on.
            metas: Optional mapping of name -> metadata dict.

        """
        self.function_names = list(names)
        self.function_meta = dict(metas) if metas else {}

    def get_function_meta(self, name: str) -> dict[str, Any]:
        """Get metadata for a function breakpoint.

        Args:
            name: The function name.

        Returns:
            The metadata dict (empty dict if not found).

        """
        return self.function_meta.get(name, {})

    def clear_function_breakpoints(self) -> None:
        """Clear all function breakpoints."""
        self.function_names.clear()
        self.function_meta.clear()

    def has_function_breakpoints(self) -> bool:
        """Check if any function breakpoints are set."""
        return bool(self.function_names) or bool(self.function_meta)

    # --- Custom Breakpoint Methods ---

    def set_custom_breakpoint(
        self,
        filename: str,
        line: int,
        condition: str | None = None,
    ) -> None:
        """Set a custom (programmatic) breakpoint.

        Args:
            filename: The file path.
            line: The line number.
            condition: Optional condition expression.

        """
        if filename not in self.custom:
            self.custom[filename] = {}
        self.custom[filename][line] = condition

    def clear_custom_breakpoint(self, filename: str, line: int) -> bool:
        """Clear a custom breakpoint.

        Args:
            filename: The file path.
            line: The line number.

        Returns:
            True if a breakpoint was cleared, False if none existed.

        """
        if filename in self.custom and line in self.custom[filename]:
            del self.custom[filename][line]
            return True
        return False

    def has_custom_breakpoint(self, filename: str, line: int) -> bool:
        """Check if a custom breakpoint exists at a location.

        Args:
            filename: The file path.
            line: The line number.

        Returns:
            True if a custom breakpoint exists.

        """
        return filename in self.custom and line in self.custom[filename]

    def clear_all_custom_breakpoints(self) -> None:
        """Clear all custom breakpoints."""
        self.custom.clear()

    # --- General Methods ---

    def clear_all(self) -> None:
        """Clear all breakpoint state."""
        self.line_meta.clear()
        self._line_meta_by_path.clear()
        self.function_names.clear()
        self.function_meta.clear()
        self.custom.clear()


__all__ = ["BreakpointManager", "LineBreakpointMeta"]
