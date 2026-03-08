from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any


def format_dap_message(message: Mapping[str, Any]) -> str:
    """Return a stable JSON rendering of the complete DAP-style message."""

    return json.dumps(message, sort_keys=True)


def summarize_dap_message(message: Mapping[str, Any]) -> str:
    """Return a compact, scan-friendly summary for a DAP-style message."""

    if message.get("event") == "response":
        response_id = message.get("id")
        success = message.get("success")
        extra = _summarize_payload_keys(message, skip={"event", "id", "success", "message"})
        message_text = message.get("message")
        parts = [f"response id={response_id}", f"success={success}"]
        if message_text:
            parts.append(f"message={message_text!r}")
        if extra:
            parts.append(extra)
        return " ".join(parts)

    if "command" in message:
        args = message.get("arguments")
        request_id = message.get("id")
        parts = [f"command={message.get('command')}"]
        if request_id is not None:
            parts.append(f"id={request_id}")
        if isinstance(args, Mapping):
            arg_keys = ",".join(sorted(str(key) for key in args)) or "-"
            parts.append(f"args={arg_keys}")
        extra = _summarize_payload_keys(message, skip={"command", "id", "arguments"})
        if extra:
            parts.append(extra)
        return " ".join(parts)

    if "event" in message:
        parts = [f"event={message.get('event')}"]
        body = message.get("body")
        if isinstance(body, Mapping):
            body_keys = ",".join(sorted(str(key) for key in body)) or "-"
            parts.append(f"body={body_keys}")
        extra = _summarize_payload_keys(message, skip={"event", "body"})
        if extra:
            parts.append(extra)
        return " ".join(parts)

    return _summarize_payload_keys(message, skip=set()) or "message=<empty>"


def summarize_debugger_bdb_event(event: str, **fields: Any) -> str:
    """Return a compact summary for debugger_bdb debug logs."""

    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_debugger_bdb_field(key, value)}")
    return " ".join(parts)


def _summarize_payload_keys(message: Mapping[str, Any], *, skip: set[str]) -> str:
    extra_keys = sorted(str(key) for key in message if str(key) not in skip)
    if not extra_keys:
        return ""
    return f"fields={','.join(extra_keys)}"


def _format_debugger_bdb_field(key: str, value: Any) -> str:
    if key in {"file", "canonical"} and isinstance(value, str):
        return _short_path(value)

    if isinstance(value, Mapping):
        keys = ",".join(sorted(str(item) for item in value)) or "-"
        return f"{{{keys}}}"

    if isinstance(value, (list, tuple, set, frozenset)):
        if not value:
            return "-"
        return ",".join(_truncate_text(str(item)) for item in value)

    return _truncate_text(str(value))


def _short_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized


def _truncate_text(text: str, max_length: int = 80) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."
