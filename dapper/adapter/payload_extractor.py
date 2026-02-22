"""Payload extraction and formatting for debug events."""

from __future__ import annotations

from typing import Any


def _output(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": data.get("category", "console"),
        "output": data.get("output", ""),
        "source": data.get("source"),
        "line": data.get("line"),
        "column": data.get("column"),
    }


def _continued(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "threadId": data.get("threadId", 1),
        "allThreadsContinued": data.get("allThreadsContinued", True),
    }


def _exception(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "exceptionId": data.get("exceptionId", "Exception"),
        "description": data.get("description", ""),
        "breakMode": data.get("breakMode", "always"),
        "threadId": data.get("threadId", 1),
    }


def _breakpoint(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": data.get("reason", "changed"),
        "breakpoint": data.get("breakpoint", {}),
    }


def _module(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": data.get("reason", "new"),
        "module": data.get("module", {}),
    }


def _process(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": data.get("name", ""),
        "systemProcessId": data.get("systemProcessId"),
        "isLocalProcess": data.get("isLocalProcess", True),
        "startMethod": data.get("startMethod", "launch"),
    }


def _loaded_source(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": data.get("reason", "new"),
        "source": data.get("source", {}),
    }


def _stopped(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "reason": data.get("reason", "breakpoint"),
        "threadId": data.get("threadId", 1),
        "allThreadsStopped": data.get("allThreadsStopped", True),
    }
    if "text" in data:
        payload["text"] = data["text"]
    return payload


def _thread(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": data.get("reason", "started"),
        "threadId": data.get("threadId", 1),
    }


def _hot_reload_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "module": data.get("module", ""),
        "path": data.get("path", ""),
        "reboundFrames": data.get("reboundFrames", 0),
        "updatedFrameCodes": data.get("updatedFrameCodes", 0),
        "patchedInstances": data.get("patchedInstances", 0),
        "warnings": data.get("warnings", []),
        "durationMs": data.get("durationMs", 0.0),
    }


_EXTRACTORS: dict[str, Any] = {
    "output": _output,
    "continued": _continued,
    "exception": _exception,
    "breakpoint": _breakpoint,
    "module": _module,
    "process": _process,
    "loadedSource": _loaded_source,
    "stopped": _stopped,
    "thread": _thread,
    "dapper/hotReloadResult": _hot_reload_result,
}


def extract_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a normalized payload for the given event type.

    Returns None if the event type has no registered extractor.
    """
    extractor = _EXTRACTORS.get(event_type)
    if extractor is None:
        return None
    return extractor(data)
