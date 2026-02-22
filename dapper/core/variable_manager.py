"""VariableManager: Centralized management of variable references and Variable object creation.

This module provides a unified API for:
1. Allocating variable references (for expandable objects in the debugger UI)
2. Resolving variable references back to objects
3. Creating DAP-compliant Variable objects with proper presentation hints
"""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Union

from dapper.core.structured_model import get_model_fields
from dapper.core.structured_model import is_structured_model
from dapper.core.structured_model import structured_model_label
from dapper.protocol.debugger_protocol import PresentationHint
from dapper.protocol.debugger_protocol import Variable as VariableDict

# Type aliases matching the protocol definitions
VarRefObject = tuple[Literal["object"], Any]
VarRefScope = tuple[int, Literal["locals", "globals"]]
VarRefList = list[Any]  # list of Variable-shaped dicts
VarRef = Union[VarRefObject, VarRefScope, VarRefList]


class VariableManager:
    """Manages variable references and Variable object creation.

    This class handles:
    1. Allocation of unique reference IDs for expandable objects
    2. Storage and retrieval of referenced objects
    3. Creation of DAP-compliant Variable objects with proper hints

    Attributes:
        next_var_ref: The next reference ID to allocate.
        var_refs: Mapping of reference ID to stored reference data.

    Example usage:
        manager = VariableManager()

        # Allocate a reference for an expandable object
        ref_id = manager.allocate_ref(my_dict)

        # Create a Variable object
        var = manager.make_variable("x", 42)

        # Retrieve a referenced object
        ref_data = manager.get_ref(ref_id)

    """

    # Default starting reference ID (leaves room for reserved IDs)
    DEFAULT_START_REF = 1000

    def __init__(self, start_ref: int = DEFAULT_START_REF) -> None:
        """Initialize the variable manager.

        Args:
            start_ref: The starting reference ID for allocations.

        """
        self.next_var_ref: int = start_ref
        self.var_refs: dict[int, VarRef] = {}

    def allocate_ref(self, value: Any) -> int:
        """Allocate a variable reference for an expandable value.

        Only allocates references for objects that can be expanded:
        - Objects with __dict__
        - Dicts, lists, tuples

        Args:
            value: The value to potentially allocate a reference for.

        Returns:
            The allocated reference ID, or 0 if the value is not expandable.

        """
        if not self._is_expandable(value):
            return 0

        try:
            ref = self.next_var_ref
            self.next_var_ref = ref + 1
            self.var_refs[ref] = ("object", value)
        except Exception:
            return 0
        else:
            return ref

    def allocate_scope_ref(
        self,
        frame_id: int,
        scope: Literal["locals", "globals"],
    ) -> int:
        """Allocate a variable reference for a frame scope.

        Args:
            frame_id: The frame ID this scope belongs to.
            scope: Either "locals" or "globals".

        Returns:
            The allocated reference ID.

        """
        ref = self.next_var_ref
        self.next_var_ref = ref + 1
        self.var_refs[ref] = (frame_id, scope)
        return ref

    def get_ref(self, ref_id: int) -> VarRef | None:
        """Retrieve a stored variable reference.

        Args:
            ref_id: The reference ID to look up.

        Returns:
            The stored reference data, or None if not found.

        """
        return self.var_refs.get(ref_id)

    def has_ref(self, ref_id: int) -> bool:
        """Check if a reference ID exists.

        Args:
            ref_id: The reference ID to check.

        Returns:
            True if the reference exists.

        """
        return ref_id in self.var_refs

    def clear(self) -> None:
        """Clear all stored references and reset the counter."""
        self.var_refs.clear()
        self.next_var_ref = self.DEFAULT_START_REF

    def _is_expandable(self, value: Any) -> bool:
        """Check if a value should be expandable in the debugger UI."""
        return hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple))

    def make_variable(
        self,
        name: Any,
        value: Any,
        *,
        max_string_length: int = 1000,
        data_bp_state: Any | None = None,
        frame: Any | None = None,
    ) -> VariableDict:
        """Create a DAP-compliant Variable object.

        Args:
            name: The variable name.
            value: The variable value.
            max_string_length: Maximum length for string representation.
            data_bp_state: Optional data breakpoint state for hasDataBreakpoint detection.
            frame: Optional frame for data breakpoint context.

        Returns:
            A Variable-shaped dict with proper presentation hints.

        """
        val_str = self._format_value(value, max_string_length)
        var_ref = self.allocate_ref(value)
        type_name = type(value).__name__
        kind, attrs = self._detect_kind_and_attrs(value, max_string_length)

        # For structured models, use a descriptive type label and record the
        # number of named fields so DAP clients can render the count badge.
        named_variables: int | None = None
        if is_structured_model(value):
            type_name = structured_model_label(value)
            named_variables = len(get_model_fields(value))

        # Check for data breakpoint
        if data_bp_state is not None:
            name_str = str(name)
            frame_id = id(frame) if frame is not None else None
            if (
                data_bp_state.has_data_breakpoint_for_name(name_str, frame_id)
                and "hasDataBreakpoint" not in attrs
            ):
                attrs.append("hasDataBreakpoint")

        presentation = PresentationHint(
            kind=kind,
            attributes=attrs,
            visibility=self._get_visibility(name),
        )

        result = VariableDict(
            name=str(name),
            value=val_str,
            type=type_name,
            variablesReference=var_ref,
            presentationHint=presentation,
        )
        if named_variables is not None:
            result["namedVariables"] = named_variables
        return result

    def _format_value(self, value: Any, max_length: int) -> str:
        """Format a value for display."""
        try:
            s = repr(value)
        except Exception:
            return "<Error getting value>"
        else:
            if len(s) > max_length:
                return s[:max_length] + "..."
            return s

    def _detect_kind_and_attrs(
        self,
        value: Any,
        max_string_length: int,
    ) -> tuple[str, list[str]]:
        """Detect the kind and attributes for a value's presentation hint."""
        attrs: list[str] = []

        # Check for class type before callable (classes are callable)
        if isinstance(value, type):
            return "class", attrs

        if callable(value):
            attrs.append("hasSideEffects")
            return "method", attrs

        if isinstance(value, (list, tuple, dict, set)):
            return "data", attrs

        if isinstance(value, (str, bytes)):
            sval = value.decode() if isinstance(value, bytes) else value
            if isinstance(sval, str) and ("\n" in sval or len(sval) > max_string_length):
                attrs.append("rawString")
            return "data", attrs

        return "data", attrs

    def _get_visibility(self, name: Any) -> str:
        """Determine the visibility of a variable based on its name."""
        try:
            return "private" if str(name).startswith("_") else "public"
        except Exception:
            return "public"


__all__ = [
    "VarRef",
    "VarRefList",
    "VarRefObject",
    "VarRefScope",
    "VariableManager",
]
