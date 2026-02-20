"""Runtime source registry for dynamic / synthetic source content.

Maintains a ``sourceReference → source_string`` mapping for code objects
that have no backing filesystem file:

- ``eval`` / ``exec`` / ``compile`` strings (``co_filename == "<string>"`` etc.)
- Interactive input (``<stdin>``, ``<ipython-input-N-…>``)
- Jinja-rendered templates whose filename looks like
  ``<template /views/index.html>``
- Cython intermediates where the ``.py`` source is absent from disk
- Any code created via ``types.CodeType`` or ``importlib`` without a real path

Typical call flow
-----------------
1. The debugger encounters a frame whose ``co_filename`` is synthetic.
2. It calls :func:`annotate_stack_frames_with_source_refs` (or the
   :class:`RuntimeSourceRegistry` directly) so the source text is stored
   and the stack frame's ``source["sourceReference"]`` is populated.
3. When the DAP ``source`` request arrives,
   :meth:`~dapper.shared.debug_shared.SourceCatalog.get_source_content_by_ref`
   queries this registry before attempting a filesystem read — so the DAP
   client receives the in-memory source.

The module has *no* imports from ``dapper.shared.debug_shared`` at the module
level to avoid circular dependencies.  The :func:`annotate_stack_frames_with_source_refs`
helper lazily imports ``debug_shared`` at call time.
"""

from __future__ import annotations

import itertools
import linecache
import re
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Synthetic-filename detection
# ---------------------------------------------------------------------------

# CPython + common third-party conventions that indicate no real file path:
#   <string>           compile("…", "<string>", …)
#   <stdin>            interactive interpreter
#   <module>           top-level module execution from some shells
#   <unknown>          fallback used in several traceback formatters
#   <ipython-input-…>  IPython cells
#   <template …>       Jinja2 / Mako
#   <frozen …>         frozen modules in Python 3.11+
#   <…>                any angle-bracket-wrapped name
_SYNTHETIC_RE = re.compile(r"^<.*>$")


def is_synthetic_filename(filename: str) -> bool:
    """Return ``True`` when *filename* represents a non-filesystem code origin.

    Detects any name wrapped in angle brackets (``<string>``, ``<eval …>``,
    ``<template /index.html>``, ``<frozen importlib._bootstrap>``, …) — the
    universal CPython convention for code that has no real file on disk.

    Args:
        filename: The ``co_filename`` attribute of a code object.

    Returns:
        ``True`` if the name should be treated as a virtual / in-memory source.
    """
    return bool(_SYNTHETIC_RE.match(filename))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class RuntimeSourceEntry:
    """One entry in the :class:`RuntimeSourceRegistry`.

    Attributes:
        ref:          Integer DAP ``sourceReference``.
        virtual_path: The synthetic filename key (angle-bracket names, URIs …).
        source_text:  The complete source code as a Unicode string.
        name:         Human-readable display name shown in the DAP client UI.
        origin:       Free-form provenance tag, e.g. ``"eval"``, ``"jinja"``.
    """

    __slots__ = ("name", "origin", "ref", "source_text", "virtual_path")

    def __init__(
        self,
        ref: int,
        virtual_path: str,
        source_text: str,
        name: str | None,
        origin: str,
    ) -> None:
        self.ref = ref
        self.virtual_path = virtual_path
        self.source_text = source_text
        self.name = name or virtual_path
        self.origin = origin

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RuntimeSourceEntry(ref={self.ref!r}, virtual_path={self.virtual_path!r}, "
            f"origin={self.origin!r}, len={len(self.source_text)})"
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class RuntimeSourceRegistry:
    """Thread-safe registry of ``(sourceRef, source_text)`` pairs.

    Maintains two indices for O(1) lookup by either integer *ref* or
    *virtual_path* string.  The ref counter is independent from the one
    in :class:`~dapper.shared.debug_shared.SourceCatalog`; callers that
    need coordinated numbering should pass ``ref_hint`` when registering.

    Example::

        registry = RuntimeSourceRegistry()
        entry = registry.register("<string>", "x = 1\\n", origin="eval")
        print(entry.ref)         # 1
        print(entry.source_text) # "x = 1\\n"
        print(registry.get_source_text(entry.ref))  # "x = 1\\n"
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_id = itertools.count(1)
        self._by_ref: dict[int, RuntimeSourceEntry] = {}
        self._by_path: dict[str, RuntimeSourceEntry] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        virtual_path: str,
        source_text: str,
        *,
        name: str | None = None,
        origin: str = "dynamic",
        ref_hint: int | None = None,
    ) -> RuntimeSourceEntry:
        """Register *source_text* for *virtual_path* and return the entry.

        Idempotent: calling with the same *virtual_path* returns the existing
        entry without modifying it.  Use :meth:`update` to replace the source
        text of an already-registered path.

        Args:
            virtual_path: Synthetic filename to use as the registry key.
            source_text:  Full source content to store (Unicode).
            name:         Display name; falls back to *virtual_path*.
            origin:       Provenance tag for diagnostics (e.g. ``"eval"``).
            ref_hint:     If supplied and not already in use, adopt this
                          integer as the ``sourceReference``; otherwise a
                          fresh counter value is allocated.  Useful when the
                          caller has already allocated a ref via
                          :class:`~dapper.shared.debug_shared.SourceCatalog`.

        Returns:
            The (possibly pre-existing) :class:`RuntimeSourceEntry`.
        """
        key = virtual_path.strip()
        with self._lock:
            existing = self._by_path.get(key)
            if existing is not None:
                return existing

            if ref_hint is not None and ref_hint not in self._by_ref:
                ref: int = ref_hint
            else:
                ref = next(self._next_id)
                while ref in self._by_ref:
                    ref = next(self._next_id)

            entry = RuntimeSourceEntry(
                ref=ref,
                virtual_path=key,
                source_text=source_text,
                name=name,
                origin=origin,
            )
            self._by_ref[ref] = entry
            self._by_path[key] = entry
            return entry

    def update(self, virtual_path: str, source_text: str) -> bool:
        """Replace the stored source text for an existing entry.

        Args:
            virtual_path: The key used when the entry was registered.
            source_text:  New source content.

        Returns:
            ``True`` if the entry existed and was updated;
            ``False`` if the path is not registered (no entry is created).
        """
        key = virtual_path.strip()
        with self._lock:
            entry = self._by_path.get(key)
            if entry is None:
                return False
            entry.source_text = source_text
            return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_by_ref(self, ref: int) -> RuntimeSourceEntry | None:
        """Return the entry for *ref*, or ``None``."""
        with self._lock:
            return self._by_ref.get(ref)

    def get_by_path(self, virtual_path: str) -> RuntimeSourceEntry | None:
        """Return the entry for *virtual_path*, or ``None``."""
        with self._lock:
            return self._by_path.get(virtual_path.strip())

    def get_source_text(self, ref: int) -> str | None:
        """Return the source text for *ref*, or ``None``."""
        entry = self.get_by_ref(ref)
        return entry.source_text if entry is not None else None

    def get_source_text_by_path(self, virtual_path: str) -> str | None:
        """Return the source text for *virtual_path*, or ``None``."""
        entry = self.get_by_path(virtual_path)
        return entry.source_text if entry is not None else None

    # ------------------------------------------------------------------
    # linecache-aware convenience
    # ------------------------------------------------------------------

    def get_or_register_from_linecache(
        self,
        virtual_path: str,
        *,
        origin: str = "linecache-dynamic",
    ) -> RuntimeSourceEntry | None:
        """Attempt to resolve *virtual_path* via :mod:`linecache` and auto-register.

        Python populates ``linecache`` for every ``compile()`` call that
        uses a fake filename, so this is the primary way to obtain source
        text for ``eval``/``exec`` code.

        Args:
            virtual_path: Synthetic filename to look up.
            origin:       Provenance tag stored on the entry.

        Returns:
            The (new or existing) :class:`RuntimeSourceEntry`, or ``None``
            if ``linecache`` has no content for this path.
        """
        key = virtual_path.strip()
        existing = self.get_by_path(key)
        if existing is not None:
            return existing
        lines = linecache.getlines(key)
        if not lines:
            return None
        source_text = "".join(lines)
        return self.register(key, source_text, origin=origin)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_entries(self) -> list[RuntimeSourceEntry]:
        """Return a snapshot of all entries, ordered by ref."""
        with self._lock:
            return sorted(self._by_ref.values(), key=lambda e: e.ref)

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_ref)

    def clear(self) -> None:
        """Remove all entries.  Intended for test tear-down."""
        with self._lock:
            self._by_ref.clear()
            self._by_path.clear()


# ---------------------------------------------------------------------------
# Stack-frame annotation helper
# ---------------------------------------------------------------------------


def annotate_stack_frames_with_source_refs(
    stack_frames: list[dict[str, Any]],
) -> None:
    """Populate ``source["sourceReference"]`` for synthetic-filename frames.

    Walks *stack_frames* (a list of DAP ``StackFrame`` dicts) and, for each
    frame whose ``source["path"]`` is a synthetic filename (e.g. ``<string>``),
    attempts to look up or register the source text in the active session's
    dynamic registry.  On success, the ``sourceReference`` key is set on the
    frame's ``source`` sub-dict so DAP clients can fetch the content via the
    ``source`` request.

    The import of :mod:`dapper.shared.debug_shared` is deferred to call time
    so this module stays free of circular top-level imports.

    Args:
        stack_frames: Mutable list of DAP stack-frame dicts.  Modified in place.
    """
    if not stack_frames:
        return

    try:
        from dapper.shared.debug_shared import get_active_session  # noqa: PLC0415

        session = get_active_session()
    except Exception:
        return

    for sf in stack_frames:
        source = sf.get("source")
        if not isinstance(source, dict):
            continue

        path = source.get("path", "")
        if not path or not is_synthetic_filename(path):
            continue

        # Skip frames that already carry a sourceReference
        if source.get("sourceReference"):
            continue

        try:
            ref = session.sources.get_or_register_dynamic_from_linecache(path)
            source["sourceReference"] = ref
        except Exception:  # pragma: no cover - defensive
            pass
