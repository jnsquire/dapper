"""
Common object shapes used by many requests/responses: Source, Breakpoint, StackFrame, Scope, Variable, Thread
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired


# Source related types
class Source(TypedDict):
    """A source is a descriptor for source code."""

    name: NotRequired[str]  # The short name of the source
    path: str  # The path of the source to be shown in the UI
    sourceReference: NotRequired[
        int
    ]  # If > 0, the contents must be retrieved through the source request
    presentationHint: NotRequired[Literal["normal", "emphasize", "deemphasize"]]
    origin: NotRequired[str]  # The origin of this source
    sources: NotRequired[list[Source]]  # List of sources that are related to this source
    adapterData: NotRequired[
        Any
    ]  # Additional data that a debug adapter might want to loop through the client
    checksums: NotRequired[list[Any]]  # The checksums associated with this file


# Breakpoint related types
class SourceBreakpoint(TypedDict):
    """Properties of a breakpoint or logpoint passed to the setBreakpoints request."""

    line: int  # The source line of the breakpoint or logpoint
    column: NotRequired[int]  # Start position within source line
    condition: NotRequired[str]  # The expression for conditional breakpoints
    hitCondition: NotRequired[
        str
    ]  # The expression that controls how many hits of the breakpoint are ignored
    logMessage: NotRequired[
        str
    ]  # If this exists and is non-empty, the adapter must not 'break' but log the message


class Breakpoint(TypedDict):
    """Information about a breakpoint created in setBreakpoints, setFunctionBreakpoints, etc."""

    verified: bool  # If true, the breakpoint could be set
    message: NotRequired[str]  # A message about the state of the breakpoint
    id: NotRequired[int]  # An identifier for the breakpoint
    source: NotRequired[Source]  # The source where the breakpoint is located
    line: NotRequired[int]  # The start line of the actual range covered by the breakpoint
    column: NotRequired[int]  # Start position of the source range covered by the breakpoint
    endLine: NotRequired[int]  # The end line of the actual range covered by the breakpoint
    endColumn: NotRequired[int]  # End position of the source range covered by the breakpoint
    instructionReference: NotRequired[str]  # A memory reference to where the breakpoint is set
    offset: NotRequired[int]  # The offset from the instruction reference


# Stack trace related types
class StackFrame(TypedDict):
    """A Stackframe contains the source location."""

    id: int  # An identifier for the stack frame
    name: str  # The name of the stack frame, typically a method name
    source: NotRequired[Source]  # The source of the frame
    line: int  # The line within the source of the frame
    column: int  # Start position of the range covered by the stack frame
    endLine: NotRequired[int]  # The end line of the range covered by the stack frame
    endColumn: NotRequired[int]  # End position of the range covered by the stack frame
    canRestart: NotRequired[bool]  # Indicates whether this frame can be restarted
    instructionPointerReference: NotRequired[
        str
    ]  # A memory reference for the current instruction pointer


class Scope(TypedDict):
    """A Scope is a named container for variables."""

    name: str  # Name of the scope such as 'Arguments', 'Locals'
    presentationHint: NotRequired[Literal["arguments", "locals", "registers"]]
    variablesReference: (
        int  # The variables of this scope can be retrieved by passing this reference
    )
    namedVariables: NotRequired[int]  # The number of named variables in this scope
    indexedVariables: NotRequired[int]  # The number of indexed variables in this scope
    expensive: (
        bool  # If true, the number of variables in this scope is large or expensive to retrieve
    )
    source: NotRequired[Source]  # The source for this scope
    line: NotRequired[int]  # The start line of the range covered by this scope
    column: NotRequired[int]  # Start position of the range covered by the scope
    endLine: NotRequired[int]  # The end line of the range covered by the scope
    endColumn: NotRequired[int]  # End position of the range covered by the scope


class VariablePresentationHint(TypedDict):
    """Properties of a variable that can be used to determine how to render the variable in the UI."""

    kind: NotRequired[str]  # The kind of variable
    attributes: NotRequired[list[str]]  # Set of attributes represented as an array of strings
    visibility: NotRequired[str]  # Visibility of variable
    lazy: NotRequired[
        bool
    ]  # If true, clients can present the variable with a UI that supports a specific gesture


class Variable(TypedDict):
    """A Variable is a name/value pair."""

    name: str  # The variable's name
    value: str  # The variable's value
    type: NotRequired[str]  # The type of the variable's value
    presentationHint: NotRequired[
        VariablePresentationHint
    ]  # Properties of a variable to determine rendering
    evaluateName: NotRequired[str]  # The evaluatable name of this variable
    variablesReference: int  # If > 0, the variable is structured and its children can be retrieved
    namedVariables: NotRequired[int]  # The number of named child variables
    indexedVariables: NotRequired[int]  # The number of indexed child variables
    memoryReference: NotRequired[str]  # A memory reference associated with this variable


# Thread related types
class Thread(TypedDict):
    """A Thread."""

    id: int  # Unique identifier for the thread
    name: str  # The name of the thread
