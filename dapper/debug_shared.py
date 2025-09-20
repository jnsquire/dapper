"""Shared debug adapter state and utilities to break circular imports."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any
from typing import TypedDict

MAX_STRING_LENGTH = 1000
VAR_REF_TUPLE_SIZE = 2

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)


class SourceReferenceMetaBase(TypedDict):
    """Required fields for a sourceReference entry."""

    path: str


class SourceReferenceMeta(SourceReferenceMetaBase, total=False):
    """Optional fields for a sourceReference entry.

    Values of SessionState.source_references map to this shape.
    - path: required absolute or relative file system path
    - name: optional display name for the source
    """

    name: str | None


class SessionState:
    """
    Singleton holder for adapter state and helper methods.
    Provides session-scoped management for sourceReferences via helper methods.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Avoid reinitializing on subsequent __new__ returns
        if getattr(self, "_initialized", False):
            return

        self.debugger: Any | None = None
        self.stop_at_entry: bool = False
        self.no_debug: bool = False
        self.command_queue: list[Any] = []
        self.command_lock = threading.Lock()
        self.is_terminated: bool = False
        self.ipc_enabled: bool = False
        self.ipc_sock: Any | None = None
        self.ipc_rfile: Any | None = None
        self.ipc_wfile: Any | None = None
        self.handle_debug_command: Any | None = None  # Set by debug_adapter_comm

        # Mapping of sourceReference -> metadata (path/name)
        self.source_references: dict[int, SourceReferenceMeta] = {}
        # Reverse mapping path -> ref id
        self._path_to_ref: dict[str, int] = {}
        # Session counter for allocating new ids
        self.next_source_ref = 1

        self._initialized = True

    # Source reference helpers
    def get_ref_for_path(self, path: str) -> int | None:
        return self._path_to_ref.get(path)

    def get_or_create_source_ref(self, path: str, name: str | None = None) -> int:
        existing = self.get_ref_for_path(path)
        if existing:
            return existing
        ref = self.next_source_ref
        try:
            self.source_references[ref] = {"path": path, "name": name}
        except Exception:
            self.source_references[ref] = {"path": path}
        self._path_to_ref[path] = ref
        self.next_source_ref = ref + 1
        return ref

    def get_source_meta(self, ref: int) -> SourceReferenceMeta | None:
        return self.source_references.get(ref)

    def get_source_content_by_ref(self, ref: int) -> str | None:
        meta = self.get_source_meta(ref)
        if not meta:
            return None
        path = meta.get("path")
        if not path:
            return None
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def get_source_content_by_path(self, path: str) -> str | None:
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None


# Module-level singleton instance used throughout the codebase
state = SessionState()


def send_debug_message(event_type: str, **kwargs) -> None:
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled and state.ipc_wfile is not None:
        try:
            state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
            state.ipc_wfile.flush()
        except Exception:
            pass
        else:
            return
    send_logger.debug(json.dumps(message))
    with contextlib.suppress(Exception):
        sys.stdout.flush()
