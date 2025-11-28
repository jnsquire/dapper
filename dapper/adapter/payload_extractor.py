"""Payload extraction and formatting for debug events."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Callable


# Module-level registry mapping event name -> function object
_payload_registry: dict[str, Callable[..., dict[str, Any]]] = {}


def payload(event_name: str):
    """Decorator to mark payload-producing methods with an event name."""

    def _decorator(func: Callable[..., dict[str, Any]]):
        # Register in module-level registry keyed by event name
        _payload_registry[event_name] = func
        return func

    return _decorator


def register_payloads(cls: type):
    """Class decorator that collects @payload methods and builds dispatch mapping.

    Creates a class-level `payload_dispatch` dict mapping event_name -> method_name.
    """
    mapping: dict[str, str] = {}
    for name, member in cls.__dict__.items():
        if not callable(member):
            continue
        # Find the event name whose registered function matches this member
        for evt, func in _payload_registry.items():
            if func is member:
                mapping[evt] = name
                break
    cls.payload_dispatch = mapping
    return cls


@register_payloads
class DebugDataExtractor(dict):
    """Helper to extract and format event payloads from generic dicts.

    Subclasses dict so it can be initialized with raw event data, then
    provides typed payload extraction methods for each event type.
    """

    @payload("output")
    def output_payload(self) -> dict[str, Any]:
        return {
            "category": self.get("category", "console"),
            "output": self.get("output", ""),
            "source": self.get("source"),
            "line": self.get("line"),
            "column": self.get("column"),
        }

    @payload("continued")
    def continued_payload(self) -> dict[str, Any]:
        return {
            "threadId": self.get("threadId", 1),
            "allThreadsContinued": self.get("allThreadsContinued", True),
        }

    @payload("exception")
    def exception_payload(self) -> dict[str, Any]:
        return {
            "exceptionId": self.get("exceptionId", "Exception"),
            "description": self.get("description", ""),
            "breakMode": self.get("breakMode", "always"),
            "threadId": self.get("threadId", 1),
        }

    @payload("breakpoint")
    def breakpoint_payload(self) -> dict[str, Any]:
        return {
            "reason": self.get("reason", "changed"),
            "breakpoint": self.get("breakpoint", {}),
        }

    @payload("module")
    def module_payload(self) -> dict[str, Any]:
        return {
            "reason": self.get("reason", "new"),
            "module": self.get("module", {}),
        }

    @payload("process")
    def process_payload(self) -> dict[str, Any]:
        return {
            "name": self.get("name", ""),
            "systemProcessId": self.get("systemProcessId"),
            "isLocalProcess": self.get("isLocalProcess", True),
            "startMethod": self.get("startMethod", "launch"),
        }

    @payload("loadedSource")
    def loaded_source_payload(self) -> dict[str, Any]:
        return {
            "reason": self.get("reason", "new"),
            "source": self.get("source", {}),
        }
