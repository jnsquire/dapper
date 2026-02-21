"""Just My Code — classify stack frames as user vs library code.

Matches debugpy's ``justMyCode`` semantics: a frame is *library code* when
its source file lives inside the interpreter's standard-library / site-packages
tree, belongs to a frozen bootstrap module, or is an internal Dapper frame.

Usage
-----
Call :func:`is_user_frame` from :class:`~dapper.core.debugger_bdb.DebuggerBDB`
to decide whether to skip a frame during stepping and/or mark it as *subtle*
in a DAP ``stackTrace`` response.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types

# ---------------------------------------------------------------------------
# Interpreter prefix cache
# ---------------------------------------------------------------------------

# Resolved once per interpreter session.  Storing as a module-level variable
# (rather than a global that is mutated) makes testing simple: tests can clear
# _SYS_PREFIX_CACHE by setting it to None.
_SYS_PREFIX_CACHE: frozenset[str] | None = None


def _compute_sys_prefixes() -> frozenset[str]:
    """Return a frozenset of normalised interpreter prefix paths.

    Each entry ends with ``/`` so that plain ``str.startswith`` checks do not
    accidentally match a sibling directory whose name *starts with* the prefix
    (e.g. ``/usr`` must not match ``/usr_extra/lib``).
    """
    raw: set[str] = set()
    for attr in ("prefix", "base_prefix", "real_prefix"):  # real_prefix: virtualenv
        p = getattr(sys, attr, None)
        if p:
            raw.add(p)
    prefixes: set[str] = set()
    for p in raw:
        try:
            resolved = Path(p).resolve().as_posix()
        except Exception:
            resolved = p.replace("\\", "/")
        if not resolved.endswith("/"):
            resolved += "/"
        prefixes.add(resolved.lower())
    return frozenset(prefixes)


def _sys_prefixes() -> frozenset[str]:
    global _SYS_PREFIX_CACHE  # noqa: PLW0603
    if _SYS_PREFIX_CACHE is None:
        _SYS_PREFIX_CACHE = _compute_sys_prefixes()
    return _SYS_PREFIX_CACHE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_user_path(filename: str) -> bool:
    """Return ``True`` when *filename* should be treated as user code.

    Accepts a raw ``co_filename`` string.  All classification criteria are the
    same as :func:`is_user_frame`; this variant is useful when only the path
    string is available (e.g. when processing DAP stack-frame dicts).
    """
    # 1. Frozen bootstrap modules (importlib internals on Python 3.11+).
    if filename.startswith("<frozen ") or filename == "<frozen>":
        return False

    # Normalise separators for the remaining checks.
    norm = filename.replace("\\", "/")
    norm_lower = norm.lower()

    # 2. Third-party packages installed into site-packages / dist-packages.
    if "site-packages/" in norm_lower or "dist-packages/" in norm_lower:
        return False

    # 3. Standard library inside the interpreter prefix tree.
    for prefix in _sys_prefixes():
        if norm_lower.startswith(prefix):
            return False

    # 4. Dapper's own debugger-internal frames (bdb machinery, launcher glue).
    return "/dapper/core/" not in norm and "/dapper/launcher/" not in norm


def is_user_frame(frame: types.FrameType) -> bool:
    """Return ``True`` when *frame* should be shown as user code.

    Returns ``False`` (library / debugger frame) when the frame's source file:

    * is a frozen bootstrap module (``<frozen ...>``),
    * contains ``site-packages`` or ``dist-packages`` in the path,
    * is located inside the interpreter's stdlib / venv prefix (``sys.prefix``,
      ``sys.base_prefix``, or ``sys.real_prefix`` for virtualenv),
    * belongs to Dapper's own core or launcher machinery.

    All tests are case-insensitive and work correctly on both POSIX and Windows
    regardless of the path separator used by the interpreter.
    """
    return is_user_path(frame.f_code.co_filename)
