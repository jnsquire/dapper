from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

    from dapper.adapter.debugger.session import _PyDebuggerSessionFacade
    from dapper.core.breakpoint_manager import BreakpointManager
    from dapper.core.variable_manager import VariableManager


class _PyDebuggerSessionCompatMixin:
    """Compatibility helpers for session-backed debugger state.

    The remaining methods bridge legacy call points while using
    `_PyDebuggerSessionFacade` as the state authority.
    """

    variable_manager: VariableManager
    breakpoint_manager: BreakpointManager
    _session_facade: _PyDebuggerSessionFacade
    process: subprocess.Popen | None
    is_terminated: bool

    def _get_next_command_id(self) -> int:
        """Get the next command ID and increment the counter."""
        return self._session_facade.allocate_command_id()

    def clear_runtime_state(self) -> None:
        """Clear mutable runtime session containers in session facade.

        Clears both legacy session facade state and core managers.
        """
        self._session_facade.clear_runtime_state()
        if hasattr(self, "variable_manager"):
            self.variable_manager.var_refs.clear()
            self.variable_manager.next_var_ref = self.variable_manager.DEFAULT_START_REF
        if hasattr(self, "breakpoint_manager"):
            self.breakpoint_manager.line_meta.clear()
            self.breakpoint_manager._line_meta_by_path.clear()  # noqa: SLF001
            self.breakpoint_manager.function_names.clear()
            self.breakpoint_manager.function_meta.clear()
            self.breakpoint_manager.custom.clear()

    def _get_process_state(self) -> tuple[subprocess.Popen | None, bool]:
        """Get the current process state for the external backend."""
        return self.process, self.is_terminated
